from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import os

from app import db
from app.models import CardPriceCache, Carta, CartaPokemon
from app.services.external_price_service import fetchExternalCardPrice


DEFAULT_CACHE_TTL_HOURS = int(os.getenv("PRICE_CACHE_TTL_HOURS", "24"))
DISPLAY_PRICE_SOURCE = "Preço estimado"


def _now():
    return datetime.utcnow()


def _decimal_or_none(valor):
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def _json_dumps(valor):
    if isinstance(valor, str):
        return valor
    return json.dumps(valor, ensure_ascii=False, default=str)


def _json_loads(valor):
    if not valor:
        return None
    try:
        return json.loads(valor)
    except (TypeError, json.JSONDecodeError):
        return valor


def _resolve_card(card_id, card=None):
    if card is not None:
        return card

    if isinstance(card_id, int) or str(card_id).isdigit():
        carta = Carta.query.get(int(card_id))
        if carta:
            return carta

    return CartaPokemon.query.filter_by(api_id=str(card_id)).first()


def _cache_card_id(card, original_card_id=None):
    if isinstance(card, Carta):
        return card.external_card_id or str(card.id)
    if isinstance(card, CartaPokemon):
        return card.api_id
    return str(original_card_id)


def _card_metadata(card):
    if isinstance(card, Carta):
        return {
            "card_name": card.nome,
            "set_name": card.set_name or (card.pack.nome if card.pack else None),
            "collector_number": card.collector_number,
        }
    if isinstance(card, CartaPokemon):
        return {
            "card_name": card.nome,
            "set_name": card.colecao.nome if card.colecao else None,
            "collector_number": card.numero,
        }
    return {"card_name": None, "set_name": None, "collector_number": None}


def _is_fresh(cache, ttl_hours):
    if not cache or not cache.last_checked_at:
        return False
    return cache.last_checked_at >= _now() - timedelta(hours=ttl_hours)


def _cache_to_result(cache, *, stale=False, fallback_reason=None):
    raw_data = _json_loads(cache.raw_data) if cache else None
    price_source = raw_data.get("source") if isinstance(raw_data, dict) else None
    if cache and cache.price is not None:
        price_source = DISPLAY_PRICE_SOURCE
    return {
        "price": float(cache.price) if cache and cache.price is not None else None,
        "currency": cache.currency if cache else "BRL",
        "source": cache.source if cache else "unavailable",
        "priceSource": price_source or (cache.source if cache else "unavailable"),
        "rawData": raw_data,
        "lastCheckedAt": cache.last_checked_at.isoformat() if cache and cache.last_checked_at else None,
        "fromCache": bool(cache),
        "stale": stale,
        "fallbackReason": fallback_reason,
    }


def _unavailable_result(card_id, raw_data=None):
    return {
        "price": None,
        "currency": "BRL",
        "source": "unavailable",
        "priceSource": "unavailable",
        "rawData": raw_data or {"source": "unavailable"},
        "lastCheckedAt": None,
        "fromCache": False,
        "stale": False,
        "fallbackReason": None,
        "cardId": str(card_id),
    }


def _pack_saved_result(card):
    if not isinstance(card, Carta) or card.valor_estimado is None:
        return None

    return {
        "price": float(card.valor_estimado or 0),
        "currency": "BRL",
        "source": "pack_saved_estimate",
        "priceSource": DISPLAY_PRICE_SOURCE,
        "rawData": {
            "provider": "pack_saved_estimate",
            "source": DISPLAY_PRICE_SOURCE,
            "card_id": card.id,
        },
        "lastCheckedAt": None,
        "fromCache": False,
        "stale": False,
        "fallbackReason": "cache_missing",
        "cardId": str(card.id),
    }


def _upsert_cache(cache_card_id, source, card, external_result, checked_at=None):
    cache = CardPriceCache.query.filter_by(card_id=cache_card_id, source=source).first()
    if cache is None:
        cache = CardPriceCache(card_id=cache_card_id, source=source)
        db.session.add(cache)

    metadata = _card_metadata(card)
    cache.card_name = metadata["card_name"]
    cache.set_name = metadata["set_name"]
    cache.collector_number = metadata["collector_number"]
    cache.price = _decimal_or_none(external_result.get("price"))
    cache.currency = external_result.get("currency") or "BRL"
    cache.raw_data = _json_dumps(external_result)
    cache.last_checked_at = checked_at or _now()
    cache.updated_at = _now()
    return cache


def getCardPrice(
    cardId,
    source="default",
    *,
    allow_external=True,
    force_refresh=False,
    cache_ttl_hours=None,
    card=None,
):
    ttl_hours = int(cache_ttl_hours or os.getenv("PRICE_CACHE_TTL_HOURS", DEFAULT_CACHE_TTL_HOURS))
    resolved_card = _resolve_card(cardId, card=card)
    cache_card_id = _cache_card_id(resolved_card, cardId)
    cache = CardPriceCache.query.filter_by(card_id=cache_card_id, source=source).first()

    if cache and not force_refresh and _is_fresh(cache, ttl_hours):
        resultado = _cache_to_result(cache)
        resultado["cardId"] = cache_card_id
        return resultado

    if not allow_external:
        if cache:
            resultado = _cache_to_result(cache, stale=not _is_fresh(cache, ttl_hours))
            resultado["cardId"] = cache_card_id
            return resultado

        resultado = _pack_saved_result(resolved_card) if resolved_card else None
        return resultado or _unavailable_result(cardId)

    if resolved_card is None:
        if cache:
            resultado = _cache_to_result(cache, stale=True, fallback_reason="unavailable")
            resultado["cardId"] = cache_card_id
            return resultado
        return _unavailable_result(cardId)

    try:
        external_result = fetchExternalCardPrice(resolved_card, source=source)
        cache = _upsert_cache(cache_card_id, source, resolved_card, external_result)
        db.session.commit()
        resultado = _cache_to_result(cache)
        resultado["cardId"] = cache_card_id
        resultado["fromCache"] = False
        return resultado
    except Exception as exc:
        db.session.rollback()
        if cache:
            resultado = _cache_to_result(cache, stale=True, fallback_reason="external_unavailable")
            resultado["cardId"] = cache_card_id
            return resultado
        return _unavailable_result(cardId)


def upsertCardPriceCache(card, price, source="default", currency="BRL", raw_data=None, checked_at=None):
    cache_card_id = _cache_card_id(card)
    price_source = raw_data.get("source") if isinstance(raw_data, dict) else None
    payload = {
        "price": float(price) if price is not None else None,
        "currency": currency or "BRL",
        "source": price_source or source,
        "rawData": raw_data or {},
    }
    cache = _upsert_cache(cache_card_id, source, card, payload, checked_at=checked_at)
    return cache


def get_card_price(*args, **kwargs):
    return getCardPrice(*args, **kwargs)


def upsert_card_price_cache(*args, **kwargs):
    return upsertCardPriceCache(*args, **kwargs)
