from collections import Counter
from datetime import datetime, timedelta
import time

from app.models import CardPriceCache, Carta, Simulacao
from app.services.price_cache_service import getCardPrice


def _cache_key(carta):
    return carta.external_card_id or str(carta.id)


def _cache_vencido(cache, agora, horas=24):
    if not cache or not cache.last_checked_at:
        return True
    return cache.last_checked_at < agora - timedelta(hours=horas)


def _contar_cartas_abertas(cutoff):
    contagem = Counter()
    simulacoes = Simulacao.query.filter(Simulacao.data_simulacao >= cutoff).all()
    for simulacao in simulacoes:
        for item in simulacao.cartas_obtidas:
            carta_id = item.get("id")
            if carta_id is None:
                continue
            contagem[int(carta_id)] += int(item.get("quantidade") or 1)
    return contagem


def selecionar_cartas_relevantes(limit=500, source="default"):
    agora = datetime.utcnow()
    abertas = _contar_cartas_abertas(agora - timedelta(days=30))
    caches = {
        cache.card_id: cache
        for cache in CardPriceCache.query.filter_by(source=source).all()
    }

    candidatas = []
    for carta in Carta.query.all():
        cache = caches.get(_cache_key(carta))
        score = 0

        if abertas.get(carta.id):
            score += 1000 + abertas[carta.id]
        if cache is None:
            score += 500
        if _cache_vencido(cache, agora):
            score += 300
        if float(carta.valor_estimado or 0) >= 20:
            score += 200
        if carta.pack and carta.pack.data_criacao >= agora - timedelta(days=180):
            score += 100
        if carta.external_card_id:
            score += 50

        if score > 0:
            candidatas.append((score, carta))

    candidatas.sort(key=lambda item: item[0], reverse=True)
    return [carta for _, carta in candidatas[:limit]]


def atualizar_precos_cartas(limit=500, delay_seconds=1.0, source="default"):
    cartas = selecionar_cartas_relevantes(limit=limit, source=source)
    resumo = {
        "total": len(cartas),
        "sucesso": 0,
        "falha": 0,
        "indisponivel": 0,
    }

    for indice, carta in enumerate(cartas, start=1):
        try:
            resultado = getCardPrice(
                carta.id,
                source=source,
                allow_external=True,
                force_refresh=True,
                card=carta,
            )
            if resultado.get("price") is None:
                resumo["indisponivel"] += 1
                print(
                    f"[{indice}/{len(cartas)}] sem preco: {carta.nome} "
                    f"({resultado.get('source')})"
                )
            else:
                resumo["sucesso"] += 1
                print(
                    f"[{indice}/{len(cartas)}] atualizado: {carta.nome} "
                    f"R$ {resultado['price']:.2f} via {resultado.get('priceSource')}"
                )
        except Exception:
            resumo["falha"] += 1
            print(f"[{indice}/{len(cartas)}] falha: {carta.nome}")

        if delay_seconds and indice < len(cartas):
            time.sleep(delay_seconds)

    return resumo
