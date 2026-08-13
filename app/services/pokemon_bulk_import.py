import os
import time

from app import db
from app.models import ColecaoPokemon, Pack
from app.services.pokemon_api import PokemonAPIError, importar_cartas_da_colecao, importar_colecoes
from app.services.pokemon_pack_builder import (
    PRECO_PACK_AUTOMATICO_BRL,
    criar_ou_atualizar_pack_da_colecao,
)
from app.services.simulador import CARTAS_POR_PACK


def _intervalo_padrao():
    configurado = os.getenv("POKEMON_IMPORT_INTERVAL_SECONDS")
    if configurado is not None:
        try:
            return max(float(configurado), 0)
        except ValueError:
            pass
    return 0.25 if os.getenv("POKEMON_TCG_API_KEY") else 2.1


def criar_todos_os_packs_pokemon(
    intervalo=None,
    tentativas=3,
    progresso=None,
):
    """Sincroniza todas as colecoes e cria um pack de R$ 14,99 para cada uma."""
    intervalo = _intervalo_padrao() if intervalo is None else max(float(intervalo), 0)
    total_tentativas = max(int(tentativas), 1)
    informar = progresso or (lambda mensagem: None)

    resumo_colecoes = importar_colecoes()
    colecoes = db.session.execute(
        db.select(ColecaoPokemon).order_by(
            ColecaoPokemon.data_lancamento.desc(),
            ColecaoPokemon.nome,
        )
    ).scalars().all()
    pendentes = [colecao.api_id for colecao in colecoes]
    indice_por_api_id = {
        colecao.api_id: indice
        for indice, colecao in enumerate(colecoes, start=1)
    }
    erros = {}
    packs_criados = 0
    packs_atualizados = 0
    cartas_criadas = 0
    cartas_atualizadas = 0

    for rodada in range(1, total_tentativas + 1):
        if not pendentes:
            break

        if rodada > 1:
            informar(f"Nova tentativa para {len(pendentes)} colecao(oes) pendente(s).")
            time.sleep(min(rodada * 5, 15))

        rodada_pendentes = []
        for posicao, api_id in enumerate(pendentes, start=1):
            colecao = ColecaoPokemon.query.filter_by(api_id=api_id).first()
            if colecao is None:
                erros[api_id] = "Colecao nao encontrada depois da sincronizacao."
                rodada_pendentes.append(api_id)
                continue

            informar(
                f"[{indice_por_api_id[api_id]}/{len(colecoes)}] "
                f"Importando {colecao.nome}..."
            )
            try:
                resumo_cartas = importar_cartas_da_colecao(
                    colecao,
                    atualizar_precos_brasil=False,
                )
                pack, criado = criar_ou_atualizar_pack_da_colecao(
                    colecao,
                    preco_pack=PRECO_PACK_AUTOMATICO_BRL,
                    consultar_precos_externos=False,
                )
            except (PokemonAPIError, ValueError) as exc:
                db.session.rollback()
                erros[api_id] = str(exc)
                rodada_pendentes.append(api_id)
                informar(f"Falha em {colecao.nome}: {exc}")
            else:
                erros.pop(api_id, None)
                packs_criados += int(criado)
                packs_atualizados += int(not criado)
                cartas_criadas += resumo_cartas["criadas"]
                cartas_atualizadas += resumo_cartas["atualizadas"]
                informar(
                    f"Pack pronto: {pack.nome} | {len(pack.cartas)} cartas | R$ 14,99"
                )

            if intervalo and (posicao < len(pendentes) or rodada < total_tentativas):
                time.sleep(intervalo)

        pendentes = rodada_pendentes

    # Garante as regras do pack mesmo ao executar a rotina sobre uma base existente.
    db.session.execute(
        db.update(Pack).values(
            preco_pack=PRECO_PACK_AUTOMATICO_BRL,
            quantidade_cartas_por_pack=CARTAS_POR_PACK,
        )
    )
    db.session.commit()

    return {
        "colecoes": resumo_colecoes,
        "total_colecoes": len(colecoes),
        "packs_criados": packs_criados,
        "packs_atualizados": packs_atualizados,
        "cartas_criadas": cartas_criadas,
        "cartas_atualizadas": cartas_atualizadas,
        "falhas": [
            {"api_id": api_id, "erro": erros.get(api_id, "Falha desconhecida")}
            for api_id in pendentes
        ],
    }
