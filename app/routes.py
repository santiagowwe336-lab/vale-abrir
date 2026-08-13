from decimal import Decimal, InvalidOperation
from datetime import datetime
import json
import os

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app import db
from app.models import Carta, CartaPokemon, ColecaoPokemon, Pack, Simulacao
from app.services.pokemon_api import PokemonAPIError, importar_cartas_da_colecao, importar_colecoes
from app.services.pokemon_pack_builder import (
    PRECO_PACK_AUTOMATICO_BRL,
    buscar_pack_da_colecao,
    criar_ou_atualizar_pack_da_colecao,
)
from app.services.simulador import CARTAS_POR_PACK, simular_abertura


bp = Blueprint("main", __name__)

JOGOS = ["Pokémon", "Yu-Gi-Oh!", "One Piece", "Magic", "Outro"]
QUANTIDADES_SIMULACAO = [1, 10, 100, 1000]
LIMITE_CARTAS_REVELACAO = 60


@bp.app_context_processor
def contexto_global():
    return {"jogos_disponiveis": JOGOS, "ano_atual": datetime.utcnow().year}


@bp.app_template_filter("brl")
def filtro_brl(valor):
    numero = float(valor or 0)
    texto = f"R$ {numero:,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


@bp.app_template_filter("percentual")
def filtro_percentual(valor):
    return f"{float(valor or 0):.2f}%".replace(".", ",")


def _decimal_form(nome_campo, padrao="0"):
    valor = (request.form.get(nome_campo) or "").strip()
    if not valor:
        valor = padrao
    valor = valor.replace("R$", "").replace(" ", "")
    if "," in valor and "." in valor:
        valor = valor.replace(".", "").replace(",", ".")
    elif "," in valor:
        valor = valor.replace(",", ".")

    try:
        return Decimal(valor)
    except InvalidOperation:
        raise ValueError(f"O campo {nome_campo} precisa ser um número válido.")


def _int_form(nome_campo, padrao=0):
    valor = (request.form.get(nome_campo) or "").strip()
    if not valor:
        return padrao
    try:
        return int(valor)
    except ValueError:
        raise ValueError(f"O campo {nome_campo} precisa ser um número inteiro.")


def _preencher_pack(pack):
    pack.nome = (request.form.get("nome") or "").strip()
    pack.jogo = (request.form.get("jogo") or "Outro").strip()
    pack.descricao = (request.form.get("descricao") or "").strip()
    pack.carta_desejada_nome = (request.form.get("carta_desejada_nome") or "").strip()

    if not pack.nome:
        return "Informe o nome do pack."
    if pack.jogo not in JOGOS:
        pack.jogo = "Outro"

    try:
        pack.preco_pack = _decimal_form("preco_pack")
        pack.preco_carta_desejada_avulsa = _decimal_form("preco_carta_desejada_avulsa")
        pack.quantidade_cartas_por_pack = CARTAS_POR_PACK
    except ValueError as exc:
        return str(exc)

    if pack.preco_pack < 0:
        return "O preço do pack não pode ser negativo."
    if pack.preco_carta_desejada_avulsa < 0:
        return "O preço da carta avulsa não pode ser negativo."
    return None


def _preencher_carta(carta):
    carta.nome = (request.form.get("nome") or "").strip()
    carta.raridade = (request.form.get("raridade") or "").strip()
    carta.imagem_url = (request.form.get("imagem_url") or "").strip()
    carta.observacao = (request.form.get("observacao") or "").strip()
    carta.is_carta_desejada = request.form.get("is_carta_desejada") == "on"

    if not carta.nome:
        return "Informe o nome da carta."

    try:
        carta.valor_estimado = _decimal_form("valor_estimado")
        chance = float(_decimal_form("chance_aparicao"))
    except ValueError as exc:
        return str(exc)

    if carta.valor_estimado < 0:
        return "O valor estimado não pode ser negativo."
    if chance < 0 or chance > 100:
        return "A chance de aparição precisa estar entre 0 e 100."

    carta.chance_aparicao = chance
    return None


@bp.route("/")
def index():
    busca = (request.args.get("q") or "").strip()
    consulta = ColecaoPokemon.query
    if busca:
        consulta = consulta.filter(ColecaoPokemon.nome.ilike(f"%{busca}%"))
    colecoes = consulta.order_by(
        ColecaoPokemon.data_lancamento.desc(),
        ColecaoPokemon.nome.asc(),
    ).all()
    return render_template(
        "index.html",
        colecoes=colecoes,
        busca=busca,
        total_colecoes=ColecaoPokemon.query.count(),
    )


@bp.route("/packs")
def packs():
    lista_packs = Pack.query.order_by(Pack.data_criacao.desc()).all()
    return render_template("packs.html", packs=lista_packs)


@bp.route("/packs/novo", methods=["GET", "POST"])
def pack_novo():
    pack = Pack(jogo="Pokémon", quantidade_cartas_por_pack=CARTAS_POR_PACK)

    if request.method == "POST":
        erro = _preencher_pack(pack)
        if erro:
            flash(erro, "danger")
        else:
            db.session.add(pack)
            db.session.commit()
            flash("Pack cadastrado com sucesso.", "success")
            return redirect(url_for("main.pack_detail", pack_id=pack.id))

    return render_template("pack_form.html", pack=pack, editando=False)


@bp.route("/packs/<int:pack_id>")
def pack_detail(pack_id):
    pack = Pack.query.get_or_404(pack_id)
    return render_template("pack_detail.html", pack=pack)


@bp.route("/packs/<int:pack_id>/editar", methods=["GET", "POST"])
def pack_editar(pack_id):
    pack = Pack.query.get_or_404(pack_id)

    if request.method == "POST":
        erro = _preencher_pack(pack)
        if erro:
            flash(erro, "danger")
        else:
            db.session.commit()
            flash("Pack atualizado com sucesso.", "success")
            return redirect(url_for("main.pack_detail", pack_id=pack.id))

    return render_template("pack_form.html", pack=pack, editando=True)


@bp.route("/packs/<int:pack_id>/excluir", methods=["POST"])
def pack_excluir(pack_id):
    pack = Pack.query.get_or_404(pack_id)
    db.session.delete(pack)
    db.session.commit()
    flash("Pack excluído com sucesso.", "success")
    return redirect(url_for("main.packs"))


@bp.route("/packs/<int:pack_id>/cartas/nova", methods=["GET", "POST"])
def carta_nova(pack_id):
    pack = Pack.query.get_or_404(pack_id)
    carta = Carta(pack=pack)

    if request.method == "POST":
        erro = _preencher_carta(carta)
        if erro:
            flash(erro, "danger")
        else:
            if carta.is_carta_desejada and not pack.carta_desejada_nome:
                pack.carta_desejada_nome = carta.nome
            db.session.add(carta)
            db.session.commit()
            flash("Carta cadastrada com sucesso.", "success")
            return redirect(url_for("main.pack_detail", pack_id=pack.id))

    return render_template("carta_form.html", pack=pack, carta=carta, editando=False)


@bp.route("/cartas/<int:carta_id>/editar", methods=["GET", "POST"])
def carta_editar(carta_id):
    carta = Carta.query.get_or_404(carta_id)
    pack = carta.pack

    if request.method == "POST":
        erro = _preencher_carta(carta)
        if erro:
            flash(erro, "danger")
        else:
            if carta.is_carta_desejada:
                pack.carta_desejada_nome = carta.nome
            db.session.commit()
            flash("Carta atualizada com sucesso.", "success")
            return redirect(url_for("main.pack_detail", pack_id=pack.id))

    return render_template("carta_form.html", pack=pack, carta=carta, editando=True)


@bp.route("/cartas/<int:carta_id>/excluir", methods=["POST"])
def carta_excluir(carta_id):
    carta = Carta.query.get_or_404(carta_id)
    pack_id = carta.pack_id
    db.session.delete(carta)
    db.session.commit()
    flash("Carta excluída com sucesso.", "success")
    return redirect(url_for("main.pack_detail", pack_id=pack_id))


@bp.route("/packs/<int:pack_id>/simular", methods=["GET", "POST"])
def simular(pack_id):
    pack = Pack.query.get_or_404(pack_id)

    if request.method == "POST":
        if not pack.cartas:
            flash("Esta coleção ainda não possui cartas disponíveis para simular.", "warning")
            return redirect(url_for("main.index"))

        escolha = request.form.get("quantidade_packs", "1")
        try:
            if escolha == "personalizada":
                quantidade = _int_form("quantidade_personalizada", 1)
            else:
                quantidade = int(escolha)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("main.simular", pack_id=pack.id))

        if quantidade <= 0:
            flash("A quantidade de packs precisa ser maior que zero.", "danger")
            return redirect(url_for("main.simular", pack_id=pack.id))
        if quantidade > 10000:
            flash("Escolha no máximo 10.000 packs por simulação.", "danger")
            return redirect(url_for("main.simular", pack_id=pack.id))

        resultado = simular_abertura(pack, pack.cartas, quantidade)
        sequencia = resultado.get("cartas_reveladas", [])
        modo_destaques = len(sequencia) > LIMITE_CARTAS_REVELACAO
        if modo_destaques:
            sequencia = sorted(
                sequencia,
                key=lambda carta: float(carta.get("valor_unitario") or 0),
                reverse=True,
            )[:CARTAS_POR_PACK]
            sequencia.reverse()

        dados_cartas = {
            "resumo": resultado.get("cartas_obtidas", []),
            "sequencia": sequencia,
            "modo_destaques": modo_destaques,
        }
        simulacao = Simulacao(
            pack=pack,
            quantidade_packs=quantidade,
            custo_total=0,
            valor_total_estimado=resultado["valor_total_estimado"],
            lucro_prejuizo=0,
            chance_lucro=0,
            chance_carta_desejada=0,
            melhor_carta="",
            conclusao="",
            legenda_tiktok="",
            cartas_obtidas_json=json.dumps(dados_cartas, ensure_ascii=False),
        )
        db.session.add(simulacao)
        db.session.commit()
        return redirect(url_for("main.abrir_simulacao", simulacao_id=simulacao.id))

    return render_template(
        "simular.html",
        pack=pack,
        nome_colecao=pack.nome.removeprefix("Pokemon - ").removeprefix("Pokémon - "),
        quantidades=QUANTIDADES_SIMULACAO,
    )


@bp.route("/simulacoes/<int:simulacao_id>")
def resultado(simulacao_id):
    simulacao = Simulacao.query.get_or_404(simulacao_id)
    nome_colecao = simulacao.pack.nome.removeprefix("Pokemon - ").removeprefix("Pokémon - ")
    return render_template(
        "resultado.html",
        simulacao=simulacao,
        pack=simulacao.pack,
        nome_colecao=nome_colecao,
    )


@bp.route("/simulacoes/<int:simulacao_id>/abrir")
def abrir_simulacao(simulacao_id):
    simulacao = Simulacao.query.get_or_404(simulacao_id)
    pack = simulacao.pack
    nome_colecao = pack.nome.removeprefix("Pokemon - ").removeprefix("Pokémon - ")
    cartas = simulacao.cartas_reveladas
    modo_destaques = simulacao.revelacao_em_destaques or len(cartas) > LIMITE_CARTAS_REVELACAO

    if len(cartas) > LIMITE_CARTAS_REVELACAO:
        cartas = sorted(
            cartas,
            key=lambda carta: float(carta.get("valor_unitario") or 0),
            reverse=True,
        )[:CARTAS_POR_PACK]
        cartas.reverse()

    if not cartas:
        return redirect(url_for("main.resultado", simulacao_id=simulacao.id))

    colecao = ColecaoPokemon.query.filter_by(nome=nome_colecao).first()
    return render_template(
        "abrir_pack.html",
        simulacao=simulacao,
        pack=pack,
        colecao=colecao,
        nome_colecao=nome_colecao,
        cartas=cartas,
        modo_destaques=modo_destaques,
        cartas_por_pack=CARTAS_POR_PACK,
    )


@bp.route("/colecoes/<int:colecao_id>/simular", methods=["POST"])
def simular_colecao(colecao_id):
    colecao = ColecaoPokemon.query.get_or_404(colecao_id)
    pack = buscar_pack_da_colecao(colecao)

    if pack is not None and pack.cartas:
        if pack.quantidade_cartas_por_pack != CARTAS_POR_PACK:
            pack.quantidade_cartas_por_pack = CARTAS_POR_PACK
            db.session.commit()
        return redirect(url_for("main.simular", pack_id=pack.id))

    if not colecao.cartas:
        try:
            importar_cartas_da_colecao(colecao, atualizar_precos_brasil=False)
        except PokemonAPIError:
            flash(
                "Não foi possível preparar esta coleção agora. Tente novamente mais tarde.",
                "danger",
            )
            return redirect(url_for("main.index"))

    try:
        pack, _ = criar_ou_atualizar_pack_da_colecao(
            colecao,
            preco_pack=0,
            consultar_precos_externos=False,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.index"))

    return redirect(url_for("main.simular", pack_id=pack.id))


@bp.route("/pokemon/importar-colecoes", methods=["GET", "POST"])
def pokemon_importar_colecoes():
    if request.method == "POST":
        try:
            resumo = importar_colecoes()
            flash(
                (
                    f"Coleções importadas: {resumo['criadas']} novas, "
                    f"{resumo['atualizadas']} atualizadas."
                ),
                "success",
            )
            return redirect(url_for("main.index"))
        except PokemonAPIError as exc:
            flash("Não foi possível concluir a consulta agora. Tente novamente mais tarde.", "danger")

    return render_template(
        "importacao_pokemon.html",
        api_key_configurada=bool(os.getenv("POKEMON_TCG_API_KEY")),
    )


@bp.route("/pokemon/colecoes")
def pokemon_colecoes():
    busca = (request.args.get("q") or "").strip()
    consulta = ColecaoPokemon.query
    if busca:
        consulta = consulta.filter(ColecaoPokemon.nome.ilike(f"%{busca}%"))
    colecoes = consulta.order_by(ColecaoPokemon.data_lancamento.desc()).all()
    return render_template("colecoes_pokemon.html", colecoes=colecoes, busca=busca)


@bp.route("/pokemon/colecao/<int:colecao_id>")
def pokemon_colecao_detail(colecao_id):
    colecao = ColecaoPokemon.query.get_or_404(colecao_id)
    pagina = max(request.args.get("page", 1, type=int), 1)
    consulta = db.select(CartaPokemon).filter_by(colecao_id=colecao.id).order_by(CartaPokemon.numero)
    paginacao = db.paginate(consulta, page=pagina, per_page=24, error_out=False)
    return render_template("colecao_pokemon_detail.html", colecao=colecao, paginacao=paginacao)


@bp.route("/pokemon/importar-cartas/<int:colecao_id>", methods=["POST"])
def pokemon_importar_cartas(colecao_id):
    colecao = ColecaoPokemon.query.get_or_404(colecao_id)
    try:
        resumo = importar_cartas_da_colecao(
            colecao,
            atualizar_precos_brasil=False,
        )
        flash(
            (
                f"Cartas importadas para {colecao.nome}: {resumo['criadas']} novas, "
                f"{resumo['atualizadas']} atualizadas, {resumo['total_api']} encontradas na API."
            ),
            "success",
        )
    except PokemonAPIError as exc:
        flash("Não foi possível concluir a consulta agora. Tente novamente mais tarde.", "danger")
    return redirect(url_for("main.pokemon_colecao_detail", colecao_id=colecao.id))


@bp.route("/pokemon/colecao/<int:colecao_id>/criar-pack", methods=["POST"])
def pokemon_criar_pack_simulavel(colecao_id):
    colecao = ColecaoPokemon.query.get_or_404(colecao_id)
    atualizar_dados = request.form.get("atualizar_dados") == "on" or len(colecao.cartas) == 0

    if atualizar_dados:
        try:
            resumo = importar_cartas_da_colecao(
                colecao,
                atualizar_precos_brasil=False,
            )
            flash(
                (
                    f"Dados da coleção atualizados: {resumo['criadas']} cartas novas, "
                    f"{resumo['atualizadas']} atualizadas, {resumo['total_api']} encontradas na API."
                ),
                "success",
            )
        except PokemonAPIError as exc:
            flash("Não foi possível concluir a consulta agora. Tente novamente mais tarde.", "danger")
            return redirect(url_for("main.pokemon_colecao_detail", colecao_id=colecao.id))

    try:
        quantidade_cartas = (
            _int_form("quantidade_cartas_por_pack")
            if request.form.get("quantidade_cartas_por_pack")
            else None
        )
        pack, criado = criar_ou_atualizar_pack_da_colecao(
            colecao,
            preco_pack=PRECO_PACK_AUTOMATICO_BRL,
            quantidade_cartas_por_pack=quantidade_cartas,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.pokemon_colecao_detail", colecao_id=colecao.id))

    acao = "criado" if criado else "atualizado"
    flash(
        (
            f"Pack {acao} com {len(pack.cartas)} cartas, valores e chances preenchidos "
            "automaticamente."
        ),
        "success",
    )
    return redirect(url_for("main.simular", pack_id=pack.id))


@bp.route("/pokemon/carta/<int:carta_id>/atualizar", methods=["POST"])
def pokemon_atualizar_carta(carta_id):
    carta = CartaPokemon.query.get_or_404(carta_id)
    try:
        carta.preco_manual_brl = _decimal_form("preco_manual_brl") if request.form.get("preco_manual_brl") else None
        chance = request.form.get("chance_manual")
        carta.chance_manual = float(_decimal_form("chance_manual")) if chance else None
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.pokemon_colecao_detail", colecao_id=carta.colecao_id))

    if carta.preco_manual_brl is not None and carta.preco_manual_brl < 0:
        flash("O preço manual não pode ser negativo.", "danger")
        return redirect(url_for("main.pokemon_colecao_detail", colecao_id=carta.colecao_id))
    if carta.chance_manual is not None and (carta.chance_manual < 0 or carta.chance_manual > 100):
        flash("A chance manual precisa estar entre 0 e 100.", "danger")
        return redirect(url_for("main.pokemon_colecao_detail", colecao_id=carta.colecao_id))

    carta.is_carta_desejada = request.form.get("is_carta_desejada") == "on"
    db.session.commit()
    flash(f"Carta {carta.nome} atualizada.", "success")
    return redirect(url_for("main.pokemon_colecao_detail", colecao_id=carta.colecao_id))
