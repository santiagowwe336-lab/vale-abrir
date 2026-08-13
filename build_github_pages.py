import argparse
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import requests

from app import create_app
from app.models import ColecaoPokemon, Pack
from app.services.probabilidades_pokemon import estimar_chances_por_carta
from app.services.valores_pokemon import valor_estimado_por_raridade_brl


ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
DATA_DIR = DOCS_DIR / "data"
SETS_DIR = DATA_DIR / "sets"
RAW_CARDS_URL = (
    "https://raw.githubusercontent.com/PokemonTCG/"
    "pokemon-tcg-data/master/cards/en/{api_id}.json"
)
MARCADOR_RE = re.compile(r"\[pokemon_api_id=([^\]]+)\]")


def _nome_arquivo(api_id):
    return re.sub(r"[^a-zA-Z0-9._-]", "_", api_id) + ".json"


def _gravar_json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="\n") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, separators=(",", ":"))


def _packs_por_colecao():
    resultado = {}
    for pack in Pack.query.all():
        marcador = MARCADOR_RE.search(pack.descricao or "")
        if marcador:
            resultado[marcador.group(1)] = pack
    return resultado


def _valor_local(carta, carta_pack, taxa_usd):
    if carta_pack is not None:
        return round(float(carta_pack.valor_estimado or 0), 2)
    if carta.preco_manual_brl is not None:
        return round(float(carta.preco_manual_brl), 2)
    if carta.preco_brasil_brl is not None:
        return round(float(carta.preco_brasil_brl), 2)
    if carta.preco_api_usd is not None:
        return round(float(carta.preco_api_usd) * taxa_usd, 2)
    return float(valor_estimado_por_raridade_brl(carta.raridade)["valor"])


def _normalizar_cartas_locais(colecao, pack, taxa_usd):
    cartas_pack = {
        carta.external_card_id: carta
        for carta in (pack.cartas if pack is not None else [])
        if carta.external_card_id
    }
    total = max(len(colecao.cartas), 1)
    cartas = []
    for carta in colecao.cartas:
        carta_pack = cartas_pack.get(carta.api_id)
        chance = (
            float(carta_pack.chance_aparicao or 0)
            if carta_pack is not None
            else float(carta.chance_efetiva or (100 / total))
        )
        cartas.append(
            {
                "id": carta.api_id,
                "nome": carta.nome,
                "numero": carta.numero,
                "raridade": carta.raridade or "Sem raridade",
                "imagem": carta.imagem_pequena or carta.imagem_grande,
                "valor": _valor_local(carta, carta_pack, taxa_usd),
                "chance": round(max(chance, 0), 4),
            }
        )
    return cartas


def _baixar_cartas(api_id, sessao):
    resposta = sessao.get(
        RAW_CARDS_URL.format(api_id=api_id),
        headers={"User-Agent": "ValeAbrirStaticBuilder/1.0"},
        timeout=30,
    )
    resposta.raise_for_status()
    return resposta.json()


def _normalizar_cartas_remotas(cartas_api):
    chances = estimar_chances_por_carta(cartas_api)
    cartas = []
    for carta in cartas_api:
        imagens = carta.get("images") or {}
        raridade = carta.get("rarity") or "Sem raridade"
        cartas.append(
            {
                "id": carta.get("id"),
                "nome": carta.get("name") or "Carta sem nome",
                "numero": carta.get("number"),
                "raridade": raridade,
                "imagem": imagens.get("small") or imagens.get("large"),
                "valor": float(valor_estimado_por_raridade_brl(raridade)["valor"]),
                "chance": float((chances.get(carta.get("id")) or {}).get("chance") or 0),
            }
        )
    return cartas


def construir(fetch_missing=False):
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    SETS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "app" / "static" / "css" / "style.css", DOCS_DIR / "assets" / "style.css")

    taxa_usd = float(os.getenv("STATIC_USD_BRL_RATE", "5.00"))
    app = create_app()
    sessao = requests.Session()
    falhas = []

    with app.app_context():
        packs = _packs_por_colecao()
        colecoes_banco = ColecaoPokemon.query.order_by(
            ColecaoPokemon.data_lancamento.desc(),
            ColecaoPokemon.nome.asc(),
        ).all()
        colecoes = []

        for posicao, colecao in enumerate(colecoes_banco, start=1):
            arquivo = _nome_arquivo(colecao.api_id)
            caminho_existente = SETS_DIR / arquivo
            cartas = _normalizar_cartas_locais(
                colecao,
                packs.get(colecao.api_id),
                taxa_usd,
            )
            fonte = "local"
            snapshot_existente = []

            if not cartas and caminho_existente.exists():
                try:
                    with caminho_existente.open("r", encoding="utf-8") as arquivo_json:
                        snapshot_existente = (json.load(arquivo_json) or {}).get("cartas", [])
                except (OSError, ValueError, TypeError):
                    snapshot_existente = []

            if not cartas and snapshot_existente and not fetch_missing:
                cartas = snapshot_existente
                fonte = "snapshot"

            if not cartas and fetch_missing:
                try:
                    cartas = _normalizar_cartas_remotas(
                        _baixar_cartas(colecao.api_id, sessao)
                    )
                    fonte = "pokemon-tcg-data"
                    print(
                        f"[{posicao}/{len(colecoes_banco)}] {colecao.nome}: "
                        f"{len(cartas)} cartas baixadas.",
                        flush=True,
                    )
                except (requests.RequestException, ValueError, TypeError) as exc:
                    cartas = snapshot_existente
                    fonte = "snapshot" if snapshot_existente else "indisponivel"
                    if not snapshot_existente:
                        falhas.append({"api_id": colecao.api_id, "erro": str(exc)})
                    print(
                        f"[{posicao}/{len(colecoes_banco)}] {colecao.nome}: falhou ({exc}).",
                        flush=True,
                    )

            if cartas:
                _gravar_json(
                    SETS_DIR / arquivo,
                    {
                        "api_id": colecao.api_id,
                        "nome": colecao.nome,
                        "fonte": fonte,
                        "cartas": cartas,
                    },
                )

            colecoes.append(
                {
                    "id": colecao.api_id,
                    "nome": colecao.nome,
                    "serie": colecao.serie,
                    "lancamento": colecao.data_lancamento,
                    "total": len(cartas) or int(colecao.total_cartas or 0),
                    "logo": colecao.logo_url,
                    "simbolo": colecao.simbolo_url,
                    "arquivo": f"sets/{arquivo}" if cartas else None,
                }
            )

        _gravar_json(
            DATA_DIR / "collections.json",
            {
                "gerado_em": datetime.now(timezone.utc).isoformat(),
                "taxa_usd_brl": taxa_usd,
                "total": len(colecoes),
                "colecoes": colecoes,
            },
        )

    print(
        f"Site estático gerado: {len(colecoes)} coleções, "
        f"{sum(1 for item in colecoes if item['arquivo'])} prontas.",
        flush=True,
    )
    if falhas:
        print(f"Coleções pendentes: {len(falhas)}", flush=True)
    return falhas


def main():
    parser = argparse.ArgumentParser(description="Gera a versão estática para GitHub Pages.")
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help="Baixa do repositório pokemon-tcg-data as coleções ausentes no SQLite.",
    )
    args = parser.parse_args()
    falhas = construir(fetch_missing=args.fetch_missing)
    if falhas:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
