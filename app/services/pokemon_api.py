import os
import re
import time

import requests

from app import db
from app.models import CartaPokemon, ColecaoPokemon
from app.services.precos_brasil import PrecoBrasilError, buscar_preco_medio_brasil
from app.services.probabilidades_pokemon import estimar_chances_por_carta
from app.services.valores_pokemon import _extrair_preco_pokemon_api


BASE_URL = "https://api.pokemontcg.io/v2"


class PokemonAPIError(RuntimeError):
    pass


def _headers():
    headers = {"Accept": "application/json"}
    api_key = os.getenv("POKEMON_TCG_API_KEY")
    if api_key:
        headers["X-Api-Key"] = api_key
    return headers


def _get(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    ultimo_erro = None
    for tentativa in range(3):
        try:
            resposta = requests.get(url, headers=_headers(), params=params or {}, timeout=35)
            resposta.raise_for_status()
            return resposta.json()
        except requests.RequestException as exc:
            ultimo_erro = exc
            if tentativa < 2:
                time.sleep(1.5 * (tentativa + 1))

    raise PokemonAPIError(f"Falha ao consultar a Pokémon TCG API: {ultimo_erro}") from ultimo_erro


def _ordenacao_numero_carta(item):
    numero = str(item.get("number") or "")
    partes = re.split(r"(\d+)", numero)
    chave = tuple((0, int(parte)) if parte.isdigit() else (1, parte.lower()) for parte in partes)
    return chave, item.get("id") or ""


def buscar_colecoes_api():
    payload = _get("sets", {"pageSize": 250, "orderBy": "-releaseDate"})
    return payload.get("data", [])


def importar_colecoes():
    colecoes_api = buscar_colecoes_api()
    criadas = 0
    atualizadas = 0

    for item in colecoes_api:
        api_id = item.get("id")
        if not api_id:
            continue

        colecao = ColecaoPokemon.query.filter_by(api_id=api_id).first()
        if colecao is None:
            colecao = ColecaoPokemon(api_id=api_id)
            db.session.add(colecao)
            criadas += 1
        else:
            atualizadas += 1

        imagens = item.get("images") or {}
        colecao.nome = item.get("name") or api_id
        colecao.serie = item.get("series")
        colecao.data_lancamento = item.get("releaseDate")
        colecao.total_cartas = int(item.get("total") or 0)
        colecao.total_impresso = int(item.get("printedTotal") or item.get("total") or 0)
        colecao.codigo_myp = item.get("ptcgoCode")
        colecao.simbolo_url = imagens.get("symbol")
        colecao.logo_url = imagens.get("logo")

    db.session.commit()
    return {"criadas": criadas, "atualizadas": atualizadas, "total_api": len(colecoes_api)}


def buscar_cartas_colecao_api(api_id):
    cartas = []
    pagina = 1
    page_size = 250

    while True:
        payload = _get(
            "cards",
            {
                "q": f"set.id:{api_id}",
                "page": pagina,
                "pageSize": page_size,
            },
        )
        lote = payload.get("data", [])
        cartas.extend(lote)

        total = int(payload.get("totalCount") or len(cartas))
        if len(lote) < page_size or len(cartas) >= total:
            break
        pagina += 1

    return sorted(cartas, key=_ordenacao_numero_carta)


def _extrair_preco_api_usd(item):
    preco = _extrair_preco_pokemon_api(item)
    if preco and preco.get("moeda") == "USD":
        return float(preco["valor"])
    return None


def _aplicar_preco_brasil(carta, colecao):
    preco = buscar_preco_medio_brasil(carta.nome, colecao.nome, carta.numero)
    if not preco:
        return False

    carta.preco_brasil_brl = preco["preco"]
    carta.preco_brasil_fonte = preco["fonte"]
    carta.preco_brasil_amostras = preco["amostras"]
    carta.preco_brasil_atualizado_em = preco["atualizado_em"]
    return True


def importar_cartas_da_colecao(colecao, atualizar_precos_brasil=False):
    cartas_api = buscar_cartas_colecao_api(colecao.api_id)
    chances_estimadas = estimar_chances_por_carta(cartas_api)
    criadas = 0
    atualizadas = 0
    precos_brasil_atualizados = 0
    precos_brasil_sem_resultado = 0
    erro_preco_brasil = None

    for item in cartas_api:
        api_id = item.get("id")
        if not api_id:
            continue

        carta = CartaPokemon.query.filter_by(api_id=api_id).first()
        if carta is None:
            carta = CartaPokemon(api_id=api_id, colecao=colecao)
            db.session.add(carta)
            criadas += 1
        else:
            atualizadas += 1

        imagens = item.get("images") or {}
        set_dados = item.get("set") or {}
        if set_dados:
            colecao.total_impresso = int(set_dados.get("printedTotal") or colecao.total_impresso or 0)
            colecao.codigo_myp = set_dados.get("ptcgoCode") or colecao.codigo_myp

        carta.colecao = colecao
        carta.nome = item.get("name") or api_id
        carta.numero = item.get("number")
        carta.raridade = item.get("rarity")
        carta.imagem_pequena = imagens.get("small")
        carta.imagem_grande = imagens.get("large")
        carta.preco_api_usd = _extrair_preco_api_usd(item)
        estimativa = chances_estimadas.get(api_id) or {}
        carta.chance_estimativa = estimativa.get("chance")
        carta.chance_fonte = estimativa.get("fonte")

        if atualizar_precos_brasil and erro_preco_brasil is None:
            try:
                if _aplicar_preco_brasil(carta, colecao):
                    precos_brasil_atualizados += 1
                else:
                    precos_brasil_sem_resultado += 1
            except PrecoBrasilError as exc:
                erro_preco_brasil = str(exc)

    db.session.commit()
    return {
        "criadas": criadas,
        "atualizadas": atualizadas,
        "total_api": len(cartas_api),
        "precos_brasil_atualizados": precos_brasil_atualizados,
        "precos_brasil_sem_resultado": precos_brasil_sem_resultado,
        "erro_preco_brasil": erro_preco_brasil,
    }
