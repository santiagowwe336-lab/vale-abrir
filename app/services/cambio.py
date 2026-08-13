from decimal import Decimal, InvalidOperation
from functools import lru_cache
import os

import requests


class CambioError(RuntimeError):
    pass


def _decimal(valor):
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError):
        raise CambioError("Cotação inválida retornada pela API.")


def _moeda(moeda):
    return (moeda or "USD").strip().upper()


def _cotacao_awesomeapi(moeda_origem):
    par = f"{moeda_origem}-BRL"
    url = f"https://economia.awesomeapi.com.br/json/last/{par}"
    params = {}
    api_key = os.getenv("AWESOMEAPI_KEY")
    if api_key:
        params["token"] = api_key

    resposta = requests.get(url, params=params, timeout=10)
    resposta.raise_for_status()
    dados = resposta.json().get(par.replace("-", ""))
    if not dados:
        raise CambioError("Par de moedas não encontrado na AwesomeAPI.")

    taxa = _decimal(dados.get("bid") or dados.get("ask"))
    data = dados.get("create_date") or dados.get("timestamp")
    return {
        "taxa": taxa,
        "fonte": "AwesomeAPI",
        "data": data,
    }


def _cotacao_frankfurter(moeda_origem):
    resposta = requests.get(
        "https://api.frankfurter.dev/v2/rates",
        params={"base": moeda_origem, "quotes": "BRL"},
        timeout=10,
    )
    resposta.raise_for_status()
    payload = resposta.json()

    if isinstance(payload, list) and payload:
        item = payload[0]
        taxa = item.get("rate")
        data = item.get("date")
    else:
        taxa = (payload.get("rates") or {}).get("BRL")
        data = payload.get("date")

    return {
        "taxa": _decimal(taxa),
        "fonte": "Frankfurter",
        "data": data,
    }


@lru_cache(maxsize=24)
def cotacao_para_brl(moeda_origem="USD"):
    moeda_origem = _moeda(moeda_origem)
    if moeda_origem == "BRL":
        return {"taxa": Decimal("1"), "fonte": "BRL", "data": None}

    erros = []
    for provedor in (_cotacao_awesomeapi, _cotacao_frankfurter):
        try:
            return provedor(moeda_origem)
        except (requests.RequestException, CambioError) as exc:
            erros.append(str(exc))

    env_name = f"{moeda_origem}_BRL_RATE"
    fallback = os.getenv(env_name)
    if fallback:
        return {
            "taxa": _decimal(fallback.replace(",", ".")),
            "fonte": f"{env_name} manual",
            "data": None,
        }

    raise CambioError(f"Não foi possível buscar cotação {moeda_origem}/BRL. {' | '.join(erros)}")


def converter_para_brl(valor, moeda_origem="USD"):
    cotacao = cotacao_para_brl(moeda_origem)
    convertido = _decimal(valor) * cotacao["taxa"]
    return convertido.quantize(Decimal("0.01")), cotacao

