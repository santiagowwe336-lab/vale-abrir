from functools import lru_cache
import os

import requests


class ValorPokemonError(RuntimeError):
    pass


POKEMON_API_BASE_URL = "https://api.pokemontcg.io/v2"

VALOR_PADRAO_RARIDADE_BRL = {
    "common": 0.50,
    "uncommon": 1.00,
    "rare": 2.50,
    "rare holo": 6.00,
    "rare holo ex": 12.00,
    "double rare": 12.00,
    "rare ultra": 25.00,
    "ultra rare": 25.00,
    "illustration rare": 35.00,
    "special illustration rare": 90.00,
    "hyper rare": 120.00,
    "rare secret": 120.00,
}


def _headers_pokemon_api():
    headers = {"Accept": "application/json"}
    api_key = os.getenv("POKEMON_TCG_API_KEY")
    if api_key:
        headers["X-Api-Key"] = api_key
    return headers


def _normalizar(texto):
    return (texto or "").strip().lower()


def _primeiro_valor(dados, chaves):
    for chave in chaves:
        valor = dados.get(chave)
        if valor is not None:
            return valor
    return None


def _extrair_tcgplayer(pricing):
    tcgplayer = pricing.get("tcgplayer") or {}
    for variante in ("holofoil", "normal", "reverse-holofoil", "1st-edition", "unlimited"):
        dados = tcgplayer.get(variante) or {}
        valor = _primeiro_valor(dados, ("marketPrice", "midPrice", "lowPrice"))
        if valor is not None:
            return {
                "valor": valor,
                "moeda": tcgplayer.get("unit") or "USD",
                "fonte": f"TCGdex/TCGplayer {variante}",
                "atualizado_em": tcgplayer.get("updated"),
            }
    return None


def _extrair_cardmarket(pricing):
    cardmarket = pricing.get("cardmarket") or {}
    valor = _primeiro_valor(cardmarket, ("avg", "trend", "avg7", "avg30", "low"))
    if valor is None:
        return None

    return {
        "valor": valor,
        "moeda": cardmarket.get("unit") or "EUR",
        "fonte": "TCGdex/Cardmarket",
        "atualizado_em": cardmarket.get("updated"),
    }


@lru_cache(maxsize=1500)
def buscar_valor_tcgdx(api_id):
    if not api_id:
        return None

    url = f"https://api.tcgdex.net/v2/en/cards/{api_id}"
    try:
        resposta = requests.get(url, timeout=12)
        resposta.raise_for_status()
    except requests.RequestException as exc:
        raise ValorPokemonError(f"Falha ao buscar valor no TCGdex: {exc}") from exc

    pricing = (resposta.json() or {}).get("pricing") or {}
    if not pricing:
        return None

    return _extrair_tcgplayer(pricing) or _extrair_cardmarket(pricing)


def _extrair_preco_pokemon_api(card):
    tcgplayer = card.get("tcgplayer") or {}
    precos = tcgplayer.get("prices") or {}
    for variante in ("holofoil", "normal", "reverseHolofoil", "1stEditionHolofoil", "unlimitedHolofoil"):
        dados = precos.get(variante) or {}
        valor = _primeiro_valor(dados, ("market", "mid", "low"))
        if valor is not None:
            return {
                "valor": valor,
                "moeda": "USD",
                "fonte": f"Pokémon TCG API/TCGplayer {variante}",
                "atualizado_em": (tcgplayer.get("updatedAt") or card.get("set", {}).get("updatedAt")),
            }

    cardmarket = card.get("cardmarket") or {}
    precos_cardmarket = cardmarket.get("prices") or {}
    valor = _primeiro_valor(precos_cardmarket, ("averageSellPrice", "trendPrice", "avg7", "avg30", "lowPrice"))
    if valor is not None:
        return {
            "valor": valor,
            "moeda": "EUR",
            "fonte": "Pokémon TCG API/Cardmarket",
            "atualizado_em": cardmarket.get("updatedAt"),
        }

    return None


def _buscar_card_pokemon_api(api_id):
    resposta = requests.get(
        f"{POKEMON_API_BASE_URL}/cards/{api_id}",
        headers=_headers_pokemon_api(),
        timeout=12,
    )
    resposta.raise_for_status()
    return (resposta.json() or {}).get("data") or {}


@lru_cache(maxsize=1500)
def buscar_valor_pokemon_tcg_api(api_id):
    erros = []

    if api_id:
        try:
            card = _buscar_card_pokemon_api(api_id)
            valor = _extrair_preco_pokemon_api(card)
            if valor:
                return valor
        except requests.RequestException as exc:
            erros.append(f"ID {api_id}: {exc}")

    if erros:
        raise ValorPokemonError("Falha ao buscar valor na Pokémon TCG API: " + " | ".join(erros))
    return None


def valor_estimado_por_raridade_brl(raridade):
    raridade_normalizada = _normalizar(raridade)
    valor = VALOR_PADRAO_RARIDADE_BRL.get(raridade_normalizada)
    if valor is None:
        valor = 1.00
    return {
        "valor": valor,
        "moeda": "BRL",
        "fonte": f"Estimativa local por raridade ({raridade or 'sem raridade'})",
        "atualizado_em": None,
    }
