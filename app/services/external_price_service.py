from decimal import Decimal

from app.models import Carta, CartaPokemon, ColecaoPokemon
from app.services.cambio import CambioError, converter_para_brl
from app.services.tcgcsv_price_service import TcgcsvPriceError, buscar_preco_tcgcsv
from app.services.valores_pokemon import (
    ValorPokemonError,
    buscar_valor_pokemon_tcg_api,
    buscar_valor_tcgdx,
)


SOURCE_LABEL = "Preço estimado"


class ExternalPriceError(RuntimeError):
    pass


def _decimal(valor):
    return Decimal(str(valor)) if valor is not None else None


def _as_card_id(card):
    return getattr(card, "external_card_id", None) or getattr(card, "api_id", None)


def _resolve_pokemon_card(card):
    if isinstance(card, CartaPokemon):
        return card

    external_card_id = _as_card_id(card)
    if external_card_id:
        carta_pokemon = CartaPokemon.query.filter_by(api_id=external_card_id).first()
        if carta_pokemon:
            return carta_pokemon

    if isinstance(card, Carta) and card.external_card_id:
        colecao_api_id = card.external_card_id.split("-", 1)[0]
        colecao = ColecaoPokemon.query.filter_by(api_id=colecao_api_id).first()
        if colecao:
            return CartaPokemon(
                api_id=card.external_card_id,
                colecao=colecao,
                nome=card.nome,
                numero=card.collector_number,
                raridade=card.raridade,
            )

    return None


def _result(price, raw_data, provider):
    return {
        "price": float(price) if price is not None else None,
        "currency": "BRL",
        "source": SOURCE_LABEL,
        "rawData": {
            "source": SOURCE_LABEL,
            "provider": provider,
            **(raw_data or {}),
        },
    }


def _fetch_stored_usd(carta_pokemon):
    if carta_pokemon.preco_api_usd is None:
        return None

    valor_brl, cotacao = converter_para_brl(carta_pokemon.preco_api_usd, "USD")
    return _result(
        valor_brl,
        {
            "price_original": float(carta_pokemon.preco_api_usd),
            "currency_original": "USD",
            "conversion_rate": float(cotacao["taxa"]),
            "conversion_date": cotacao.get("data"),
        },
        "pokemon_tcg_api_import",
    )


def _fetch_tcgcsv(carta_pokemon):
    valor = buscar_preco_tcgcsv(carta_pokemon)
    if not valor:
        return None

    valor_brl, cotacao = converter_para_brl(valor["valor"], valor["moeda"])
    return _result(
        valor_brl,
        {
            "price_original": float(valor["valor"]),
            "currency_original": valor["moeda"],
            "updated_at": valor.get("atualizado_em"),
            "conversion_rate": float(cotacao["taxa"]),
            "conversion_date": cotacao.get("data"),
            "tcgcsv": valor.get("raw"),
        },
        "tcgcsv_tcgplayer",
    )


def _fetch_pokemon_api(carta_pokemon):
    valor = buscar_valor_pokemon_tcg_api(carta_pokemon.api_id)
    if not valor:
        return None

    valor_brl, cotacao = converter_para_brl(valor["valor"], valor["moeda"])
    return _result(
        valor_brl,
        {
            "price_original": float(valor["valor"]),
            "currency_original": valor["moeda"],
            "updated_at": valor.get("atualizado_em"),
            "conversion_rate": float(cotacao["taxa"]),
            "conversion_date": cotacao.get("data"),
        },
        "pokemon_tcg_api",
    )


def _fetch_tcgdx(carta_pokemon):
    valor = buscar_valor_tcgdx(carta_pokemon.api_id)
    if not valor:
        return None

    valor_brl, cotacao = converter_para_brl(valor["valor"], valor["moeda"])
    return _result(
        valor_brl,
        {
            "price_original": float(valor["valor"]),
            "currency_original": valor["moeda"],
            "updated_at": valor.get("atualizado_em"),
            "conversion_rate": float(cotacao["taxa"]),
            "conversion_date": cotacao.get("data"),
        },
        "tcgdex",
    )


def _fetch_pack_saved_estimate(card):
    if not isinstance(card, Carta) or card.valor_estimado is None:
        return None

    return _result(
        _decimal(card.valor_estimado),
        {
            "card_id": card.id,
            "value": float(card.valor_estimado or 0),
        },
        "pack_saved_estimate",
    )


def fetchExternalCardPrice(card, source="default"):
    carta_pokemon = _resolve_pokemon_card(card)

    tentativas = []
    if source in ("market_live", "tcgcsv"):
        tentativas.append(("tcgcsv_tcgplayer", _fetch_tcgcsv))
    if source == "pokemon_tcg_api_live":
        tentativas.append(("pokemon_tcg_api", _fetch_pokemon_api))
    if source in ("default", "international", "pokemon_tcg_api"):
        tentativas.append(("tcgcsv_tcgplayer", _fetch_tcgcsv))
        tentativas.append(("pokemon_tcg_api", _fetch_pokemon_api))
        tentativas.append(("pokemon_tcg_api_import", _fetch_stored_usd))
    if source in ("default", "international", "tcgdex"):
        tentativas.append(("tcgdex", _fetch_tcgdx))

    if carta_pokemon:
        for nome, funcao in tentativas:
            try:
                resultado = funcao(carta_pokemon)
                if resultado and resultado.get("price") is not None:
                    resultado["selectedProvider"] = nome
                    return resultado
            except (TcgcsvPriceError, ValorPokemonError, CambioError, ExternalPriceError):
                continue

    if source in ("default", "pack_saved_estimate"):
        resultado = _fetch_pack_saved_estimate(card)
        if resultado and resultado.get("price") is not None:
            resultado["selectedProvider"] = "pack_saved_estimate"
            return resultado

    return {
        "price": None,
        "currency": "BRL",
        "source": "unavailable",
        "rawData": {"source": "unavailable"},
        "selectedProvider": "unavailable",
    }


def fetch_external_card_price(card, source="default"):
    return fetchExternalCardPrice(card, source=source)
