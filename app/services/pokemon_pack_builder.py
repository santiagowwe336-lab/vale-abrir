import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app import db
from app.models import CardPriceCache, Carta, Pack
from app.services.cambio import CambioError, cotacao_para_brl
from app.services.external_price_service import fetchExternalCardPrice
from app.services.valores_pokemon import valor_estimado_por_raridade_brl
from app.services.simulador import CARTAS_POR_PACK


MARCADOR_COLECAO = "[pokemon_api_id={api_id}]"
PRECO_PACK_AUTOMATICO_BRL = Decimal("14.99")
FONTE_PRECO_PADRAO = "Preço estimado"
PROVEDORES_EXATOS = {
    "tcgcsv_tcgplayer",
    "pokemon_tcg_api",
    "tcgdex",
}
PROVEDORES_INTERNACIONAIS = PROVEDORES_EXATOS | {"pokemon_tcg_api_import"}


def _decimal_valor(valor, padrao="0"):
    try:
        return Decimal(str(valor or padrao).replace(",", "."))
    except InvalidOperation:
        return Decimal(str(padrao))


def _cotacao_usd_para_brl():
    try:
        return cotacao_para_brl("USD")
    except CambioError:
        return None


def _raw_data_cache(cache):
    if not cache or not cache.raw_data:
        return {}
    try:
        return json.loads(cache.raw_data)
    except (TypeError, json.JSONDecodeError):
        return {}


def _cache_tem_preco_internacional(cache):
    provider, moeda_original = _cache_provider_e_moeda(cache)
    return provider in PROVEDORES_INTERNACIONAIS or moeda_original in {"USD", "EUR"}


def _cache_tem_preco_exato(cache):
    provider, moeda_original = _cache_provider_e_moeda(cache)
    return provider in PROVEDORES_EXATOS or (provider != "pokemon_tcg_api_import" and moeda_original in {"USD", "EUR"})


def _cache_provider_e_moeda(cache):
    raw_data = _raw_data_cache(cache)
    if not isinstance(raw_data, dict):
        return None, None

    provider = raw_data.get("selectedProvider") or raw_data.get("provider")
    nested = raw_data.get("rawData")
    if isinstance(nested, dict):
        provider = provider or nested.get("provider")

    moeda_original = raw_data.get("currency_original")
    if isinstance(nested, dict):
        moeda_original = moeda_original or nested.get("currency_original")

    return provider, moeda_original


def _cache_para_resultado(cache):
    if not cache or cache.price is None:
        return None
    return Decimal(str(cache.price)), FONTE_PRECO_PADRAO


def _cache_da_carta(carta_pokemon, cache_por_card_id):
    cache = cache_por_card_id.get(carta_pokemon.api_id)
    if cache is None:
        cache = CardPriceCache(card_id=carta_pokemon.api_id, source="default")
        db.session.add(cache)
        cache_por_card_id[carta_pokemon.api_id] = cache
    return cache


def _salvar_resultado_cache(carta_pokemon, resultado, cache_por_card_id):
    if not resultado or resultado.get("price") is None:
        return

    cache = _cache_da_carta(carta_pokemon, cache_por_card_id)
    agora = datetime.utcnow()
    cache.card_name = carta_pokemon.nome
    cache.set_name = carta_pokemon.colecao.nome if carta_pokemon.colecao else None
    cache.collector_number = carta_pokemon.numero
    cache.price = Decimal(str(resultado["price"]))
    cache.currency = resultado.get("currency") or "BRL"
    cache.raw_data = json.dumps(resultado, ensure_ascii=False, default=str)
    cache.last_checked_at = agora
    cache.updated_at = agora


def _resultado_preco_usd_salvo(carta_pokemon, cotacao_usd):
    if carta_pokemon.preco_api_usd is None or not cotacao_usd:
        return None

    valor = (Decimal(str(carta_pokemon.preco_api_usd)) * cotacao_usd["taxa"]).quantize(Decimal("0.01"))
    return {
        "price": float(valor),
        "currency": "BRL",
        "source": FONTE_PRECO_PADRAO,
        "rawData": {
            "source": FONTE_PRECO_PADRAO,
            "provider": "pokemon_tcg_api_import",
            "price_original": float(carta_pokemon.preco_api_usd),
            "currency_original": "USD",
            "conversion_rate": float(cotacao_usd["taxa"]),
            "conversion_date": cotacao_usd.get("data"),
        },
        "selectedProvider": "pokemon_tcg_api_import",
    }


def _valor_estimado_brl(
    carta_pokemon,
    cotacao_usd=None,
    cache_por_card_id=None,
    consultar_precos_externos=True,
):
    if cache_por_card_id is None:
        cache_por_card_id = {}
    cache = cache_por_card_id.get(carta_pokemon.api_id)
    if cache and _cache_tem_preco_exato(cache):
        resultado_cache = _cache_para_resultado(cache)
        if resultado_cache:
            return resultado_cache

    if consultar_precos_externos:
        try:
            resultado_externo = fetchExternalCardPrice(carta_pokemon, source="market_live")
            if resultado_externo.get("price") is not None:
                _salvar_resultado_cache(carta_pokemon, resultado_externo, cache_por_card_id)
                return Decimal(str(resultado_externo["price"])), FONTE_PRECO_PADRAO
        except Exception:
            pass

    if cache and _cache_tem_preco_internacional(cache):
        resultado_cache = _cache_para_resultado(cache)
        if resultado_cache:
            return resultado_cache

    resultado_usd_salvo = _resultado_preco_usd_salvo(carta_pokemon, cotacao_usd)
    if resultado_usd_salvo:
        _salvar_resultado_cache(carta_pokemon, resultado_usd_salvo, cache_por_card_id)
        return Decimal(str(resultado_usd_salvo["price"])), FONTE_PRECO_PADRAO

    valor_raridade = valor_estimado_por_raridade_brl(carta_pokemon.raridade)
    return Decimal(str(valor_raridade["valor"])), "Estimativa automatica"


def _chance_aparicao(carta_pokemon, total_cartas):
    if carta_pokemon.chance_manual is not None:
        return float(carta_pokemon.chance_manual), "Chance manual"

    if carta_pokemon.chance_estimativa is not None:
        return float(carta_pokemon.chance_estimativa), carta_pokemon.chance_fonte or "Chance estimada"

    if total_cartas:
        return round(100 / total_cartas, 4), "Estimativa uniforme por falta de raridade"

    return 0, "Sem chance automatica disponivel"


def _carta_desejada(colecao):
    cartas_desejadas = [carta for carta in colecao.cartas if carta.is_carta_desejada]
    return cartas_desejadas[0] if cartas_desejadas else None


def buscar_pack_da_colecao(colecao):
    marcador = MARCADOR_COLECAO.format(api_id=colecao.api_id)
    return Pack.query.filter(Pack.descricao.like(f"%{marcador}%")).first()


def criar_ou_atualizar_pack_da_colecao(
    colecao,
    preco_pack=None,
    quantidade_cartas_por_pack=None,
    consultar_precos_externos=True,
):
    total_cartas = len(colecao.cartas)
    if total_cartas == 0:
        raise ValueError("Importe as cartas da colecao antes de criar o pack simulavel.")

    marcador = MARCADOR_COLECAO.format(api_id=colecao.api_id)
    nome_pack = f"Pokemon - {colecao.nome}"
    preco_pack = (
        _decimal_valor(preco_pack)
        if preco_pack is not None
        else PRECO_PACK_AUTOMATICO_BRL
    )
    pack = buscar_pack_da_colecao(colecao)
    criado = pack is None
    if pack is None:
        pack = Pack(jogo="Pokemon")

    desejada = _carta_desejada(colecao)
    cotacao_usd = _cotacao_usd_para_brl()
    card_ids = [carta.api_id for carta in colecao.cartas if carta.api_id]
    caches = CardPriceCache.query.filter(
        CardPriceCache.source == "default",
        CardPriceCache.card_id.in_(card_ids),
    ).all() if card_ids else []
    cache_por_card_id = {cache.card_id: cache for cache in caches}
    preco_desejada = Decimal("0")
    if desejada:
        preco_desejada, _ = _valor_estimado_brl(
            desejada,
            cotacao_usd,
            cache_por_card_id,
            consultar_precos_externos=consultar_precos_externos,
        )

    pack.nome = nome_pack
    pack.jogo = "Pokemon"
    pack.descricao = (
        f"Pack gerado automaticamente da colecao Pokemon {colecao.nome}. "
        f"{marcador} "
        "Cartas, chances e valores foram resolvidos e gravados no momento do cadastro do pack."
    )
    pack.preco_pack = max(preco_pack, Decimal("0"))
    pack.quantidade_cartas_por_pack = CARTAS_POR_PACK
    pack.carta_desejada_nome = desejada.nome if desejada else ""
    pack.preco_carta_desejada_avulsa = max(preco_desejada, Decimal("0"))

    if criado:
        db.session.add(pack)

    pack.cartas.clear()
    for carta_pokemon in colecao.cartas:
        valor, fonte_valor = _valor_estimado_brl(
            carta_pokemon,
            cotacao_usd,
            cache_por_card_id,
            consultar_precos_externos=consultar_precos_externos,
        )
        chance, fonte_chance = _chance_aparicao(carta_pokemon, total_cartas)
        observacao = (
            f"Gerada da colecao {colecao.nome}. "
            f"Valor: {fonte_valor}. "
            f"Fonte da chance: {fonte_chance}."
        )

        carta_pack = Carta(
            external_card_id=carta_pokemon.api_id,
            nome=carta_pokemon.nome,
            set_name=colecao.nome,
            collector_number=carta_pokemon.numero,
            raridade=carta_pokemon.raridade,
            valor_estimado=max(valor, Decimal("0")),
            chance_aparicao=max(min(chance, 100), 0),
            imagem_url=carta_pokemon.imagem_pequena or carta_pokemon.imagem_grande,
            is_carta_desejada=carta_pokemon.is_carta_desejada,
            observacao=observacao,
        )
        pack.cartas.append(carta_pack)

    db.session.commit()
    return pack, criado
