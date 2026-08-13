from decimal import Decimal, InvalidOperation
from functools import lru_cache
from urllib.parse import quote
import os
import re

import requests


class MypCardsError(RuntimeError):
    pass


BASE_URL = "https://mypcards.com"
READER_PREFIX = os.getenv(
    "MYP_CARDS_READER_PREFIX",
    "https://r.jina.ai/http://",
)


def _env_bool(nome, padrao=False):
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _url_reader(url):
    if not READER_PREFIX:
        return url
    return f"{READER_PREFIX}{url}"


@lru_cache(maxsize=600)
def _baixar_markdown(url):
    try:
        resposta = requests.get(
            _url_reader(url),
            headers={"User-Agent": "ValeAbrir/1.0"},
            timeout=int(os.getenv("MYP_CARDS_TIMEOUT", "25")),
        )
        resposta.raise_for_status()
    except requests.RequestException as exc:
        raise MypCardsError(f"Falha ao consultar MYP Cards: {exc}") from exc

    conteudo = resposta.text or ""
    if "Just a moment" in conteudo and "Cloudflare" in conteudo:
        raise MypCardsError("MYP Cards retornou protecao Cloudflare para a requisicao direta.")
    return conteudo


def _limpar_texto(texto):
    return re.sub(r"\s+", " ", (texto or "").replace("####", " ")).strip()


def _codigo_colecao(carta_pokemon):
    colecao = getattr(carta_pokemon, "colecao", None)
    codigo = getattr(colecao, "codigo_myp", None)
    if codigo:
        return str(codigo).strip()

    api_id = getattr(carta_pokemon, "api_id", "") or ""
    if "-" in api_id:
        return api_id.split("-", 1)[0]
    return api_id


def _total_impresso(carta_pokemon):
    colecao = getattr(carta_pokemon, "colecao", None)
    for atributo in ("total_impresso", "total_cartas"):
        valor = getattr(colecao, atributo, None)
        if valor:
            return str(valor)
    return None


def _numero_carta(carta_pokemon):
    numero = getattr(carta_pokemon, "numero", None)
    if numero:
        return str(numero)

    api_id = getattr(carta_pokemon, "api_id", "") or ""
    if "-" in api_id:
        return api_id.rsplit("-", 1)[-1]
    return api_id


def _canon_parte_numero(valor):
    valor = str(valor or "").strip().upper()
    if valor.isdigit():
        return str(int(valor))
    return valor.lstrip("0") or valor


def _canon_numero(numero, total=None):
    texto = str(numero or "").strip().upper().replace("_", "/")
    if "/" in texto:
        esquerda, direita = texto.split("/", 1)
        return _canon_parte_numero(esquerda), _canon_parte_numero(direita)

    total_texto = str(total or "").strip()
    return _canon_parte_numero(texto), _canon_parte_numero(total_texto)


def _parse_decimal_brl(valor):
    texto = str(valor or "").strip()
    texto = texto.replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def _extrair_dinheiros(texto):
    return [
        valor
        for valor in (_parse_decimal_brl(match) for match in re.findall(r"R\$\s*[\d.,]+", texto or ""))
        if valor is not None
    ]


@lru_cache(maxsize=400)
def _edicao_myp_por_codigo(codigo):
    codigo_alvo = str(codigo or "").strip().upper()
    if not codigo_alvo:
        return None

    paginas = int(os.getenv("MYP_CARDS_EDICOES_PAGINAS", "8"))
    for pagina in range(1, paginas + 1):
        url = f"{BASE_URL}/pokemon/edicoes?page={pagina}&per-page=48"
        try:
            markdown = _baixar_markdown(url)
        except MypCardsError:
            if pagina > 1:
                return None
            raise

        for match in re.finditer(
            r"###\s+\[(?P<texto>.*?)\]\((?P<url>https://mypcards\.com/pokemon/[^)\s\"]+)",
            markdown,
            flags=re.DOTALL,
        ):
            texto = _limpar_texto(match.group("texto"))
            link = match.group("url")
            tokens = {
                token.upper()
                for token in re.findall(r"\b[A-Za-z0-9-]{2,12}\b", texto)
                if not token.isdigit()
            }
            if codigo_alvo in tokens:
                return {"url": link, "texto": texto}

    return None


def _slug_manual(codigo):
    chave = re.sub(r"[^A-Za-z0-9]", "_", str(codigo or "")).upper()
    return os.getenv(f"MYP_CARDS_COLLECTION_SLUG_{chave}") or os.getenv(f"MYP_CARDS_COLECAO_SLUG_{chave}")


def _url_colecao_myp(codigo):
    codigo = str(codigo or "").strip()
    if not codigo:
        return None

    slug = _slug_manual(codigo)
    if slug:
        return f"{BASE_URL}/pokemon/{slug.strip('/')}"

    entrada = _edicao_myp_por_codigo(codigo)
    if entrada:
        return entrada["url"]
    return None


def _extrair_codigo_numero_imagem(texto):
    match = re.search(
        r"pokemo(?:n|mn)_(?P<codigo>[a-z0-9-]+)_(?P<num>[a-z0-9]+)(?:_(?P<total>[a-z0-9]+))?",
        texto or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None

    codigo = match.group("codigo")
    total = match.group("total")
    numero = match.group("num")
    if total:
        numero = f"{numero}/{total}"
    return codigo, numero


def _extrair_numero_titulo(texto):
    titulo = re.search(r"###\s+(.+?)(?:\n|$)", texto or "", flags=re.DOTALL)
    if not titulo:
        return None

    parenteses = re.findall(r"\(([A-Za-z0-9-]+(?:/[A-Za-z0-9-]+)?)\)", titulo.group(1))
    return parenteses[-1] if parenteses else None


def _extrair_preco_historico(markdown):
    preferencias = (
        r"Mediana\s*\(Prim[aá]rio\)\s*(R\$\s*[\d.,]+)",
        r"Último Preço Vendido\s*(R\$\s*[\d.,]+)",
        r"Ultimo Preco Vendido\s*(R\$\s*[\d.,]+)",
        r"TCG Player\s*(R\$\s*[\d.,]+)",
    )
    for padrao in preferencias:
        match = re.search(padrao, markdown or "", flags=re.IGNORECASE)
        if match:
            valor = _parse_decimal_brl(match.group(1))
            if valor is not None:
                return valor
    return None


def _parsear_produtos_colecao(markdown, codigo_colecao, total):
    codigo_alvo = str(codigo_colecao or "").strip().upper()
    produtos = {}

    for match in re.finditer(
        r"\]\((?P<url>https://mypcards\.com/pokemon/produto/(?P<id>\d+)/[^)]+)\)(?P<bloco>.*?)(?=\n\*\s+!\[Image|\n Subir|\Z)",
        markdown or "",
        flags=re.DOTALL,
    ):
        texto = match.group(0)
        bloco = match.group("bloco")
        codigo_img, numero_img = _extrair_codigo_numero_imagem(texto)
        codigo = (codigo_img or "").upper()
        if codigo and codigo != codigo_alvo:
            continue
        if not codigo and not re.search(rf"\b{re.escape(codigo_alvo)}\b", bloco or "", flags=re.IGNORECASE):
            continue

        numero = numero_img or _extrair_numero_titulo(bloco)
        if not numero:
            continue

        dinheiros = _extrair_dinheiros(bloco)
        preco_listagem = dinheiros[-1] if dinheiros else None
        produto_url = match.group("url")
        produto_id = match.group("id")
        produtos[_canon_numero(numero, total)] = {
            "produto_id": produto_id,
            "produto_url": produto_url,
            "preco_url": produto_url.replace("/produto/", "/preco/") + "?dias=30",
            "preco_listagem": preco_listagem,
        }

    return produtos


@lru_cache(maxsize=120)
def _indice_colecao(codigo, total):
    url = _url_colecao_myp(codigo)
    if not url:
        raise MypCardsError(f"Edicao MYP Cards nao encontrada para o codigo {codigo}.")

    produtos = {}
    max_paginas = int(os.getenv("MYP_CARDS_COLECAO_MAX_PAGINAS", "12"))
    produtos_por_pagina = int(os.getenv("MYP_CARDS_PRODUTOS_POR_PAGINA", "30"))
    for pagina in range(1, max_paginas + 1):
        pagina_url = url if pagina == 1 else f"{url}?page={pagina}"
        try:
            markdown = _baixar_markdown(pagina_url)
        except MypCardsError:
            if pagina > 1 and produtos:
                break
            raise
        produtos_pagina = _parsear_produtos_colecao(markdown, codigo, total)
        novos = {
            chave: produto
            for chave, produto in produtos_pagina.items()
            if chave not in produtos
        }
        produtos.update(novos)
        if pagina > 1 and not novos:
            break
        if len(produtos_pagina) < produtos_por_pagina:
            break

    if not produtos:
        raise MypCardsError(f"Nenhum produto MYP Cards encontrado para a edicao {codigo}.")

    return {
        "url": url,
        "produtos": produtos,
    }


def _preco_historico(produto):
    if not _env_bool("MYP_CARDS_USAR_HISTORICO", True):
        return None

    try:
        markdown = _baixar_markdown(produto["preco_url"])
    except MypCardsError:
        return None
    return _extrair_preco_historico(markdown)


def buscar_valor_mypcards(carta_pokemon):
    codigo = _codigo_colecao(carta_pokemon)
    total = _total_impresso(carta_pokemon)
    numero = _numero_carta(carta_pokemon)
    if not codigo or not numero:
        return None

    indice = _indice_colecao(codigo.upper(), str(total or ""))
    produto = indice["produtos"].get(_canon_numero(numero, total))
    if not produto:
        raise MypCardsError(
            f"Carta {codigo} {numero}/{total or '?'} nao encontrada na edicao exata da MYP Cards."
        )

    valor_historico = _preco_historico(produto)
    if valor_historico is not None:
        return {
            "valor": valor_historico,
            "moeda": "BRL",
            "fonte": f"MYP Cards historico 30 dias do produto exato {produto['produto_id']}",
            "url": produto["preco_url"],
            "atualizado_em": None,
        }

    if produto["preco_listagem"] is None:
        return None

    return {
        "valor": produto["preco_listagem"],
        "moeda": "BRL",
        "fonte": f"MYP Cards listagem da edicao exata {codigo.upper()} ({quote(indice['url'], safe=':/')})",
        "url": produto["produto_url"],
        "atualizado_em": None,
    }
