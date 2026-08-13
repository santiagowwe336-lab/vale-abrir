from functools import lru_cache
from decimal import Decimal, InvalidOperation
import os
import re
import time
import unicodedata

import requests


TCGCSV_BASE_URL = "https://tcgcsv.com/tcgplayer"
POKEMON_CATEGORY_ID = 3
USER_AGENT = os.getenv("TCGCSV_USER_AGENT", "ValeAbrir/1.0")


class TcgcsvPriceError(RuntimeError):
    pass


def _headers():
    return {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def _get_json(url):
    last_error = None
    for tentativa in range(3):
        try:
            resposta = requests.get(url, headers=_headers(), timeout=25)
            resposta.raise_for_status()
            return resposta.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(0.2 * (tentativa + 1))
    raise TcgcsvPriceError(f"Falha ao consultar TCGCSV: {last_error}")


def _normalizar_texto(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    texto = texto.lower()
    texto = texto.replace("&", " and ")
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _normalizar_set(nome):
    nome = _normalizar_texto(nome)
    nome = re.sub(r"^(sv|swsh|sm|xy|bw|dp|ex|pl|hgss|me)\s*\d*\s+", "", nome)
    nome = re.sub(r"^(scarlet violet|sword shield)\s+", "", nome)
    return nome.strip()


def _normalizar_numero(numero):
    texto = str(numero or "").strip()
    if "/" in texto:
        texto = texto.split("/", 1)[0]
    texto = texto.replace("#", "").strip()
    match = re.search(r"\d+[a-zA-Z]?", texto)
    if not match:
        return _normalizar_texto(texto)
    valor = match.group(0)
    numero_match = re.match(r"0*(\d+)([a-zA-Z]?)", valor)
    if not numero_match:
        return valor.lower()
    return f"{int(numero_match.group(1))}{numero_match.group(2).lower()}"


def _decimal(valor):
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _grupos_pokemon():
    url = f"{TCGCSV_BASE_URL}/{POKEMON_CATEGORY_ID}/groups"
    return (_get_json(url).get("results") or [])


def _pontuar_grupo(grupo, colecao_nome, data_lancamento=None):
    alvo = _normalizar_set(colecao_nome)
    nome = _normalizar_set(grupo.get("name"))
    abrev = _normalizar_set(grupo.get("abbreviation"))

    score = 0
    if alvo and nome == alvo:
        score += 100
    elif alvo and (alvo in nome or nome in alvo):
        score += 70
    if alvo and abrev and (abrev == alvo or abrev in alvo):
        score += 15

    publicado = (grupo.get("publishedOn") or "")[:10]
    if data_lancamento and publicado == str(data_lancamento)[:10]:
        score += 25

    return score


@lru_cache(maxsize=512)
def buscar_grupo_tcgcsv(colecao_nome, data_lancamento=None):
    grupos = _grupos_pokemon()
    candidatos = [
        (_pontuar_grupo(grupo, colecao_nome, data_lancamento), grupo)
        for grupo in grupos
    ]
    candidatos = [item for item in candidatos if item[0] > 0]
    if not candidatos:
        return None
    candidatos.sort(key=lambda item: item[0], reverse=True)
    return candidatos[0][1]


@lru_cache(maxsize=256)
def _produtos_do_grupo(group_id):
    url = f"{TCGCSV_BASE_URL}/{POKEMON_CATEGORY_ID}/{group_id}/products"
    return (_get_json(url).get("results") or [])


@lru_cache(maxsize=256)
def _precos_do_grupo(group_id):
    url = f"{TCGCSV_BASE_URL}/{POKEMON_CATEGORY_ID}/{group_id}/prices"
    return (_get_json(url).get("results") or [])


def _extended_data(produto):
    dados = {}
    for item in produto.get("extendedData") or []:
        nome = item.get("name") or item.get("displayName")
        if nome:
            dados[_normalizar_texto(nome)] = item.get("value")
    return dados


def _produto_numero(produto):
    dados = _extended_data(produto)
    return _normalizar_numero(
        dados.get("number")
        or dados.get("card number")
        or dados.get("cardnumber")
        or dados.get("collector number")
    )


def _produto_raridade(produto):
    dados = _extended_data(produto)
    return _normalizar_texto(dados.get("rarity"))


def _pontuar_produto(produto, carta):
    numero_carta = _normalizar_numero(getattr(carta, "numero", None) or getattr(carta, "collector_number", None))
    nome_carta = _normalizar_texto(getattr(carta, "nome", None))
    raridade_carta = _normalizar_texto(getattr(carta, "raridade", None))

    numero_produto = _produto_numero(produto)
    nome_produto = _normalizar_texto(produto.get("cleanName") or produto.get("name"))
    raridade_produto = _produto_raridade(produto)

    score = 0
    if numero_carta and numero_produto == numero_carta:
        score += 120
    elif numero_carta and numero_carta in nome_produto:
        score += 40

    if nome_carta and nome_produto == nome_carta:
        score += 80
    elif nome_carta and (nome_carta in nome_produto or nome_produto in nome_carta):
        score += 45

    if raridade_carta and raridade_produto == raridade_carta:
        score += 15

    return score


def _produto_para_carta(group_id, carta):
    produtos = _produtos_do_grupo(int(group_id))
    candidatos = [(_pontuar_produto(produto, carta), produto) for produto in produtos]
    candidatos = [item for item in candidatos if item[0] >= 100]
    if not candidatos:
        return None
    candidatos.sort(key=lambda item: item[0], reverse=True)
    return candidatos[0][1]


def _precos_por_produto(group_id, product_id):
    return [
        preco
        for preco in _precos_do_grupo(int(group_id))
        if int(preco.get("productId") or 0) == int(product_id)
    ]


def _valor_preco(preco):
    for chave in ("marketPrice", "midPrice", "lowPrice"):
        valor = _decimal(preco.get(chave))
        if valor is not None and valor > 0:
            return valor, chave
    return None, None


def _preferencias_subtipo(raridade):
    raridade = _normalizar_texto(raridade)
    if raridade in {"common", "uncommon"}:
        return ("normal", "holofoil", "reverse holofoil")
    if "rare" in raridade or "holo" in raridade or "ex" in raridade:
        return ("holofoil", "normal", "reverse holofoil")
    return ("normal", "holofoil", "reverse holofoil")


def _escolher_preco(precos, raridade):
    precos_validos = []
    for preco in precos:
        valor, campo = _valor_preco(preco)
        if valor is None:
            continue
        precos_validos.append((preco, valor, campo, _normalizar_texto(preco.get("subTypeName"))))

    if not precos_validos:
        return None

    preferencias = _preferencias_subtipo(raridade)
    for subtipo_preferido in preferencias:
        for preco, valor, campo, subtipo in precos_validos:
            if subtipo == subtipo_preferido:
                return preco, valor, campo

    precos_validos.sort(key=lambda item: item[1], reverse=True)
    preco, valor, campo, _ = precos_validos[0]
    return preco, valor, campo


def buscar_preco_tcgcsv(carta):
    colecao = getattr(carta, "colecao", None)
    if not colecao:
        return None

    grupo = buscar_grupo_tcgcsv(colecao.nome, getattr(colecao, "data_lancamento", None))
    if not grupo:
        return None

    produto = _produto_para_carta(grupo["groupId"], carta)
    if not produto:
        return None

    precos = _precos_por_produto(grupo["groupId"], produto["productId"])
    escolhido = _escolher_preco(precos, getattr(carta, "raridade", None))
    if not escolhido:
        return None

    preco, valor, campo = escolhido
    return {
        "valor": valor,
        "moeda": "USD",
        "fonte": "TCGCSV/TCGplayer",
        "atualizado_em": grupo.get("modifiedOn"),
        "raw": {
            "group": grupo,
            "product": produto,
            "price": preco,
            "price_field": campo,
        },
    }
