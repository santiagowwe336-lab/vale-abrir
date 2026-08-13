import random
from collections import Counter


CARTAS_POR_PACK = 6


def _valor_monetario(valor):
    return float(valor or 0)


def _opcoes_de_sorteio(cartas):
    pesos = [max(float(carta.chance_aparicao or 0), 0.0) for carta in cartas]
    total = sum(pesos)

    if total <= 0:
        return cartas, [1.0 for _ in cartas]

    return list(cartas), pesos


def _preco_da_carta(carta):
    return _valor_monetario(carta.valor_estimado)


def _nivel_raridade(carta):
    raridade = (carta.raridade or "").lower()
    if any(termo in raridade for termo in ("special", "secret", "hyper", "shiny", "illustration")):
        return 5
    if any(termo in raridade for termo in ("ultra", "rainbow", "gold")):
        return 4
    if "double rare" in raridade or "dupla rara" in raridade:
        return 3
    if any(termo in raridade for termo in ("rare", "rara", "holo")):
        return 2
    if any(termo in raridade for termo in ("uncommon", "incomum")):
        return 1
    return 0


def _serializar_carta(carta):
    return {
        "id": carta.id,
        "nome": carta.nome,
        "raridade": carta.raridade or "Sem raridade",
        "imagem_url": carta.imagem_url,
        "valor_unitario": round(_preco_da_carta(carta), 2),
    }


def _ordenar_para_revelacao(sorteadas):
    ordenadas = []
    for inicio in range(0, len(sorteadas), CARTAS_POR_PACK):
        cartas_do_pack = sorteadas[inicio : inicio + CARTAS_POR_PACK]
        ordenadas.extend(
            sorted(
                cartas_do_pack,
                key=lambda carta: (_nivel_raridade(carta), _preco_da_carta(carta)),
            )
        )
    return ordenadas


def _resumir_cartas_sorteadas(sorteadas):
    contagem = Counter(carta.id for carta in sorteadas)
    cartas_por_id = {carta.id: carta for carta in sorteadas}
    resumo = []

    for carta_id, quantidade in contagem.items():
        carta = cartas_por_id[carta_id]
        valor_unitario = _preco_da_carta(carta)
        resumo.append(
            {
                "id": carta.id,
                "nome": carta.nome,
                "raridade": carta.raridade or "Sem raridade",
                "imagem_url": carta.imagem_url,
                "quantidade": quantidade,
                "valor_unitario": round(valor_unitario, 2),
                "valor_total": round(valor_unitario * quantidade, 2),
            }
        )

    return sorted(
        resumo,
        key=lambda item: (item["valor_unitario"], item["valor_total"], item["quantidade"]),
        reverse=True,
    )


def simular_abertura(pack, cartas, quantidade_packs):
    cartas = list(cartas)
    quantidade_packs = max(int(quantidade_packs or 1), 1)
    total_sorteios = quantidade_packs * CARTAS_POR_PACK

    if not cartas:
        return {
            "quantidade_packs": quantidade_packs,
            "valor_total_estimado": 0,
            "cartas_obtidas": [],
            "cartas_reveladas": [],
            "sorteios_sem_carta": total_sorteios,
        }

    opcoes_sorteio, pesos = _opcoes_de_sorteio(cartas)
    resultado_bruto = random.choices(opcoes_sorteio, weights=pesos, k=total_sorteios)
    cartas_sorteadas = list(resultado_bruto)
    cartas_reveladas = _ordenar_para_revelacao(cartas_sorteadas)
    valor_total_estimado = sum(_preco_da_carta(carta) for carta in cartas_sorteadas)

    return {
        "quantidade_packs": quantidade_packs,
        "valor_total_estimado": round(valor_total_estimado, 2),
        "cartas_obtidas": _resumir_cartas_sorteadas(cartas_sorteadas),
        "cartas_reveladas": [_serializar_carta(carta) for carta in cartas_reveladas],
        "sorteios_sem_carta": 0,
    }
