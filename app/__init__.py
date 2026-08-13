import os

from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

from config import Config


db = SQLAlchemy()
migrate = Migrate()


def _ensure_sqlite_schema(app):
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        return

    inspector = inspect(db.engine)
    tabelas = set(inspector.get_table_names())
    migracoes = {
        "cartas": {
            "external_card_id": "VARCHAR(120)",
            "set_name": "VARCHAR(180)",
            "collector_number": "VARCHAR(30)",
        },
        "cartas_pokemon": {
            "preco_brasil_brl": "NUMERIC(10, 2)",
            "preco_brasil_fonte": "VARCHAR(120)",
            "preco_brasil_amostras": "INTEGER",
            "preco_brasil_atualizado_em": "DATETIME",
            "chance_estimativa": "FLOAT",
            "chance_fonte": "VARCHAR(180)",
        },
        "colecoes_pokemon": {
            "total_impresso": "INTEGER",
            "codigo_myp": "VARCHAR(40)",
        },
        "simulacoes": {
            "cartas_obtidas_json": "TEXT",
        },
    }

    with db.engine.begin() as conexao:
        for tabela, novas_colunas in migracoes.items():
            if tabela not in tabelas:
                continue
            colunas = {coluna["name"] for coluna in inspector.get_columns(tabela)}
            for nome, tipo in novas_colunas.items():
                if nome not in colunas:
                    conexao.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}"))

        if "packs" in tabelas:
            conexao.execute(
                text(
                    "UPDATE packs SET quantidade_cartas_por_pack = 6 "
                    "WHERE quantidade_cartas_por_pack IS NULL "
                    "OR quantidade_cartas_por_pack <> 6"
                )
            )


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    from app.routes import bp

    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()
        _ensure_sqlite_schema(app)

    return app
