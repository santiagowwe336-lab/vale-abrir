import argparse

from app import create_app, db
from app.models import ColecaoPokemon
from app.services.pokemon_api import (
    PokemonAPIError,
    importar_cartas_da_colecao,
    importar_colecoes,
)
from app.services.pokemon_bulk_import import criar_todos_os_packs_pokemon
from app.services.pokemon_pack_builder import criar_ou_atualizar_pack_da_colecao


def main():
    parser = argparse.ArgumentParser(description="Importar dados da Pokémon TCG API.")
    parser.add_argument(
        "--colecao-id",
        type=int,
        help="ID local da coleção para importar cartas.",
    )
    parser.add_argument(
        "--colecao-api-id",
        help="ID da coleção na API para importar cartas, como base1 ou sv1.",
    )
    parser.add_argument(
        "--sem-preco-brasil",
        action="store_true",
        help="Mantido por compatibilidade; a importação automática usa preço internacional.",
    )
    parser.add_argument(
        "--criar-pack",
        action="store_true",
        help="Cria ou atualiza um pack simulável com todas as cartas importadas.",
    )
    parser.add_argument(
        "--preco-pack",
        help="Preço do pack em BRL; o padrão para packs automáticos é R$ 14,99.",
    )
    parser.add_argument(
        "--cartas-por-pack",
        type=int,
        help="Quantidade de cartas por pack para o pack simulável.",
    )
    parser.add_argument(
        "--todos-os-packs",
        action="store_true",
        help="Importa todas as coleções, suas cartas e cria todos os packs por R$ 14,99.",
    )
    parser.add_argument(
        "--limpar-banco",
        action="store_true",
        help="Apaga os dados locais antes da importação completa.",
    )
    parser.add_argument(
        "--intervalo",
        type=float,
        help="Intervalo entre coleções; sem API key o padrão é 2,1 segundos.",
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        try:
            if args.limpar_banco:
                if not args.todos_os_packs:
                    raise SystemExit("Use --limpar-banco junto com --todos-os-packs.")
                db.drop_all()
                db.create_all()
                print("Banco local limpo e recriado.", flush=True)

            if args.todos_os_packs:
                resumo = criar_todos_os_packs_pokemon(
                    intervalo=args.intervalo,
                    progresso=lambda mensagem: print(mensagem, flush=True),
                )
                print(
                    f"Concluído: {resumo['packs_criados']} packs criados, "
                    f"{resumo['packs_atualizados']} atualizados e "
                    f"{resumo['cartas_criadas']} cartas importadas.",
                    flush=True,
                )
                if resumo["falhas"]:
                    detalhes = ", ".join(item["api_id"] for item in resumo["falhas"])
                    raise SystemExit(f"Importação incompleta. Pendentes: {detalhes}")
                return

            if args.colecao_id or args.colecao_api_id:
                consulta = ColecaoPokemon.query
                if args.colecao_id:
                    colecao = consulta.get(args.colecao_id)
                else:
                    colecao = consulta.filter_by(api_id=args.colecao_api_id).first()

                if colecao is None:
                    raise SystemExit("Coleção não encontrada. Importe as coleções primeiro.")

                resumo = importar_cartas_da_colecao(
                    colecao,
                    atualizar_precos_brasil=False,
                )
                print(
                    f"Cartas de {colecao.nome}: {resumo['criadas']} novas, "
                    f"{resumo['atualizadas']} atualizadas."
                )

                if args.criar_pack:
                    pack, criado = criar_ou_atualizar_pack_da_colecao(
                        colecao,
                        preco_pack=args.preco_pack,
                        quantidade_cartas_por_pack=args.cartas_por_pack,
                    )
                    acao = "criado" if criado else "atualizado"
                    print(f"Pack {acao}: {pack.nome} com {len(pack.cartas)} cartas.")
            else:
                resumo = importar_colecoes()
                print(
                    f"Coleções: {resumo['criadas']} novas, "
                    f"{resumo['atualizadas']} atualizadas."
                )
        except PokemonAPIError as exc:
            raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
