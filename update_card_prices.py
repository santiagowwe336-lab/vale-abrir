import argparse

from app import create_app
from app.services.price_update_service import atualizar_precos_cartas


def main():
    parser = argparse.ArgumentParser(description="Atualiza o cache local de precos de cartas.")
    parser.add_argument("--limit", type=int, default=500, help="Limite de cartas por execucao.")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay entre consultas externas, em segundos.")
    parser.add_argument("--source", default="default", help="Fonte de preco/cache a atualizar.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        resumo = atualizar_precos_cartas(
            limit=max(args.limit, 1),
            delay_seconds=max(args.delay, 0),
            source=args.source,
        )

    print(
        "Resumo: "
        f"{resumo['sucesso']} sucesso, "
        f"{resumo['indisponivel']} indisponivel, "
        f"{resumo['falha']} falha, "
        f"{resumo['total']} total."
    )


if __name__ == "__main__":
    main()
