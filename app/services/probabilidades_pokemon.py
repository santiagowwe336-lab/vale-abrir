import unicodedata
from collections import Counter


FONTE_ESTIMATIVA = "Estimativa local por raridade; pull rate fisico oficial nao fornecido pela API"


RARIDADES_COM_SLOTS_FIXOS = {
    "common": 4,
    "uncommon": 3,
}


CHANCE_RARIDADE_POR_PACK = {
    "rare": 45.0,
    "rare holo": 28.0,
    "rare holo ex": 12.5,
    "double rare": 12.5,
    "rare ultra": 6.5,
    "ultra rare": 6.5,
    "illustration rare": 7.5,
    "special illustration rare": 1.2,
    "hyper rare": 0.75,
    "rare secret": 1.0,
    "rare rainbow": 1.0,
    "rare shiny": 4.0,
    "shiny rare": 4.0,
    "shiny ultra rare": 1.5,
    "amazing rare": 4.0,
    "ace spec rare": 5.0,
    "trainer gallery rare holo": 8.0,
}


def _normalizar(texto):
    texto = (texto or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(caractere for caractere in texto if not unicodedata.combining(caractere))


def _chance_com_slots(quantidade_cartas, slots):
    if quantidade_cartas <= 0:
        return None
    chance_nao_sair = ((quantidade_cartas - 1) / quantidade_cartas) ** slots
    return (1 - chance_nao_sair) * 100


def _chance_por_raridade(raridade, quantidade_na_raridade, total_cartas):
    raridade_normalizada = _normalizar(raridade)

    slots = RARIDADES_COM_SLOTS_FIXOS.get(raridade_normalizada)
    if slots:
        return _chance_com_slots(quantidade_na_raridade, slots)

    chance_raridade = CHANCE_RARIDADE_POR_PACK.get(raridade_normalizada)
    if chance_raridade and quantidade_na_raridade:
        return chance_raridade / quantidade_na_raridade

    if total_cartas:
        return 100 / total_cartas

    return None


def estimar_chances_por_carta(cartas_api):
    raridades = [item.get("rarity") or "Sem raridade" for item in cartas_api]
    contagem_raridades = Counter(_normalizar(raridade) for raridade in raridades)
    total_cartas = len(cartas_api)

    chances = {}
    for item in cartas_api:
        api_id = item.get("id")
        raridade = item.get("rarity") or "Sem raridade"
        raridade_normalizada = _normalizar(raridade)
        quantidade_na_raridade = contagem_raridades[raridade_normalizada]
        chance = _chance_por_raridade(raridade, quantidade_na_raridade, total_cartas)
        chances[api_id] = {
            "chance": round(chance, 4) if chance is not None else None,
            "fonte": FONTE_ESTIMATIVA,
        }

    return chances

