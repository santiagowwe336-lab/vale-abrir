import os
import statistics
import unicodedata
from datetime import datetime

import requests


class PrecoBrasilError(RuntimeError):
    pass


PALAVRAS_BLOQUEADAS = {
    "booster",
    "box",
    "deck",
    "display",
    "etb",
    "fichario",
    "graded",
    "lata",
    "lote",
    "pack",
    "pacote",
    "proxy",
    "psa",
    "cgc",
    "selado",
}


def _normalizar(texto):
    texto = (texto or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(caractere for caractere in texto if not unicodedata.combining(caractere))


def _headers():
    headers = {
        "Accept": "application/json",
        "User-Agent": "ValeAbrir/1.0",
    }
    token = os.getenv("MERCADO_LIVRE_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _query(carta_nome, colecao_nome, numero):
    partes = ["carta pokemon", carta_nome]
    if numero:
        partes.append(str(numero))
    if colecao_nome:
        partes.append(colecao_nome)
    return " ".join(partes)


def _titulo_parece_carta(resultado, carta_nome):
    titulo = _normalizar(resultado.get("title"))
    if not titulo:
        return False

    if any(palavra in titulo for palavra in PALAVRAS_BLOQUEADAS):
        return False

    tokens_nome = [token for token in _normalizar(carta_nome).split() if len(token) > 2]
    if not tokens_nome:
        return True

    tokens_encontrados = sum(1 for token in tokens_nome if token in titulo)
    return tokens_encontrados >= max(1, min(2, len(tokens_nome)))


def _media_aparada(valores):
    if not valores:
        return None
    if len(valores) < 4:
        return statistics.mean(valores)

    ordenados = sorted(valores)
    corte = max(int(len(ordenados) * 0.15), 1)
    aparados = ordenados[corte:-corte] or ordenados
    return statistics.mean(aparados)


def buscar_preco_medio_brasil(carta_nome, colecao_nome=None, numero=None):
    url = os.getenv(
        "MERCADO_LIVRE_SEARCH_URL",
        "https://api.mercadolibre.com/sites/MLB/search",
    )
    limite = int(os.getenv("MERCADO_LIVRE_MAX_RESULTADOS", "20"))
    params = {
        "q": _query(carta_nome, colecao_nome, numero),
        "limit": limite,
    }

    try:
        resposta = requests.get(url, headers=_headers(), params=params, timeout=12)
        resposta.raise_for_status()
    except requests.RequestException as exc:
        raise PrecoBrasilError(f"Falha ao consultar preco Brasil: {exc}") from exc

    resultados = resposta.json().get("results", [])
    valores = []
    for resultado in resultados:
        preco = resultado.get("price")
        if preco is None or not _titulo_parece_carta(resultado, carta_nome):
            continue
        valores.append(float(preco))

    media = _media_aparada(valores)
    if media is None:
        return None

    return {
        "preco": round(media, 2),
        "amostras": len(valores),
        "fonte": "Mercado Livre Brasil",
        "atualizado_em": datetime.utcnow(),
    }

