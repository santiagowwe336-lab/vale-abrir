from datetime import datetime
import json

from app import db


class Pack(db.Model):
    __tablename__ = "packs"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(140), nullable=False)
    jogo = db.Column(db.String(60), nullable=False, default="Outro")
    descricao = db.Column(db.Text)
    preco_pack = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    quantidade_cartas_por_pack = db.Column(db.Integer, nullable=False, default=6)
    carta_desejada_nome = db.Column(db.String(160))
    preco_carta_desejada_avulsa = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    data_criacao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    cartas = db.relationship(
        "Carta",
        backref="pack",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="Carta.nome",
    )
    simulacoes = db.relationship(
        "Simulacao",
        backref="pack",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="desc(Simulacao.data_simulacao)",
    )

    def __repr__(self):
        return f"<Pack {self.nome}>"


class Carta(db.Model):
    __tablename__ = "cartas"

    id = db.Column(db.Integer, primary_key=True)
    pack_id = db.Column(db.Integer, db.ForeignKey("packs.id"), nullable=False)
    external_card_id = db.Column(db.String(120), index=True)
    nome = db.Column(db.String(160), nullable=False)
    set_name = db.Column(db.String(180))
    collector_number = db.Column(db.String(30))
    raridade = db.Column(db.String(80))
    valor_estimado = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    chance_aparicao = db.Column(db.Float, nullable=False, default=0)
    imagem_url = db.Column(db.String(500))
    is_carta_desejada = db.Column(db.Boolean, nullable=False, default=False)
    observacao = db.Column(db.Text)

    def __repr__(self):
        return f"<Carta {self.nome}>"


class Simulacao(db.Model):
    __tablename__ = "simulacoes"

    id = db.Column(db.Integer, primary_key=True)
    pack_id = db.Column(db.Integer, db.ForeignKey("packs.id"), nullable=False)
    quantidade_packs = db.Column(db.Integer, nullable=False)
    # Mantidos para compatibilidade com bancos antigos. O fluxo atual não calcula
    # nem exibe comparação de gasto, lucro ou chances financeiras.
    custo_total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    valor_total_estimado = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    lucro_prejuizo = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    chance_lucro = db.Column(db.Float, nullable=False, default=0)
    chance_carta_desejada = db.Column(db.Float, nullable=False, default=0)
    melhor_carta = db.Column(db.String(220))
    conclusao = db.Column(db.Text)
    legenda_tiktok = db.Column(db.Text)
    cartas_obtidas_json = db.Column(db.Text)
    data_simulacao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def _dados_cartas(self):
        if not self.cartas_obtidas_json:
            return []
        try:
            return json.loads(self.cartas_obtidas_json)
        except (TypeError, json.JSONDecodeError):
            return []

    @property
    def cartas_obtidas(self):
        dados = self._dados_cartas()
        cartas = dados.get("resumo", []) if isinstance(dados, dict) else dados
        return sorted(
            cartas,
            key=lambda carta: (
                float(carta.get("valor_unitario") or 0),
                float(carta.get("valor_total") or 0),
                int(carta.get("quantidade") or 0),
            ),
            reverse=True,
        )

    @property
    def cartas_reveladas(self):
        dados = self._dados_cartas()
        if isinstance(dados, dict):
            return dados.get("sequencia", [])

        sequencia = []
        for carta in dados:
            for _ in range(int(carta.get("quantidade") or 0)):
                sequencia.append(
                    {
                        "id": carta.get("id"),
                        "nome": carta.get("nome"),
                        "raridade": carta.get("raridade") or "Sem raridade",
                        "imagem_url": carta.get("imagem_url"),
                        "valor_unitario": float(carta.get("valor_unitario") or 0),
                    }
                )
        return sequencia

    @property
    def revelacao_em_destaques(self):
        dados = self._dados_cartas()
        return bool(dados.get("modo_destaques")) if isinstance(dados, dict) else False

    @property
    def total_cartas_obtidas(self):
        return sum(int(carta.get("quantidade") or 0) for carta in self.cartas_obtidas)

    def __repr__(self):
        return f"<Simulacao {self.quantidade_packs} packs>"


class CardPriceCache(db.Model):
    __tablename__ = "card_price_cache"
    __table_args__ = (
        db.UniqueConstraint("card_id", "source", name="uq_card_price_cache_card_source"),
    )

    id = db.Column(db.Integer, primary_key=True)
    card_id = db.Column(db.String(120), nullable=False, index=True)
    card_name = db.Column(db.String(180))
    set_name = db.Column(db.String(180))
    collector_number = db.Column(db.String(30))
    source = db.Column(db.String(80), nullable=False, default="default")
    price = db.Column(db.Numeric(12, 2))
    currency = db.Column(db.String(10), nullable=False, default="BRL")
    raw_data = db.Column(db.Text)
    last_checked_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<CardPriceCache {self.card_id} {self.source}>"


class ColecaoPokemon(db.Model):
    __tablename__ = "colecoes_pokemon"

    id = db.Column(db.Integer, primary_key=True)
    api_id = db.Column(db.String(80), nullable=False, unique=True, index=True)
    nome = db.Column(db.String(180), nullable=False)
    serie = db.Column(db.String(120))
    data_lancamento = db.Column(db.String(20))
    total_cartas = db.Column(db.Integer, nullable=False, default=0)
    total_impresso = db.Column(db.Integer)
    codigo_myp = db.Column(db.String(40), index=True)
    simbolo_url = db.Column(db.String(500))
    logo_url = db.Column(db.String(500))

    cartas = db.relationship(
        "CartaPokemon",
        backref="colecao",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="CartaPokemon.numero",
    )

    def __repr__(self):
        return f"<ColecaoPokemon {self.nome}>"


class CartaPokemon(db.Model):
    __tablename__ = "cartas_pokemon"

    id = db.Column(db.Integer, primary_key=True)
    api_id = db.Column(db.String(120), nullable=False, unique=True, index=True)
    colecao_id = db.Column(db.Integer, db.ForeignKey("colecoes_pokemon.id"), nullable=False)
    nome = db.Column(db.String(180), nullable=False)
    numero = db.Column(db.String(30))
    raridade = db.Column(db.String(100))
    imagem_pequena = db.Column(db.String(500))
    imagem_grande = db.Column(db.String(500))
    preco_api_usd = db.Column(db.Numeric(10, 2))
    preco_brasil_brl = db.Column(db.Numeric(10, 2))
    preco_brasil_fonte = db.Column(db.String(120))
    preco_brasil_amostras = db.Column(db.Integer)
    preco_brasil_atualizado_em = db.Column(db.DateTime)
    preco_manual_brl = db.Column(db.Numeric(10, 2))
    chance_estimativa = db.Column(db.Float)
    chance_fonte = db.Column(db.String(180))
    chance_manual = db.Column(db.Float)
    is_carta_desejada = db.Column(db.Boolean, nullable=False, default=False)

    @property
    def preco_brl_efetivo(self):
        return self.preco_manual_brl if self.preco_manual_brl is not None else self.preco_brasil_brl

    @property
    def chance_efetiva(self):
        return self.chance_manual if self.chance_manual is not None else self.chance_estimativa

    def __repr__(self):
        return f"<CartaPokemon {self.nome}>"
