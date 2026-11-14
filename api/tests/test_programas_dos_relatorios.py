"""Vários programas nos relatórios (#621): o parâmetro `programa` repetido, cada valor marcado
no filtro, em Tempo de tela e em Marcas."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.relatorio_de_marcas import ConsultaBigQuery as BigQueryDeMarcas
from api.relatorio_de_marcas import ConsultaEmMemoria as MemoriaDeMarcas
from api.tempo_de_tela import ConsultaBigQuery as BigQueryDeTempo
from api.tempo_de_tela import ConsultaEmMemoria as MemoriaDeTempo
from api.tests import test_relatorio_de_marcas as marcas
from api.tests import test_tempo_de_tela as tempo
from api.tests.test_passadas import AUTORIZACAO

# (rota, o que mais vai no pedido) das quatro rotas de cada relatório.
ROTAS_DO_TEMPO = [
    (tempo.ROTA, []),
    (tempo.ROTA, [("limite", "5")]),
    (tempo.ROTA, [("formato", "csv")]),
    (f"{tempo.ROTA}/videos", [("pessoa_id", "c1")]),
]
ROTAS_DAS_MARCAS = [
    (marcas.ROTA, []),
    (marcas.ROTA, [("limite", "5")]),
    (marcas.ROTA, [("formato", "csv")]),
    (f"{marcas.ROTA}/insercoes", [("marca", "Ambev")]),
]


def _tempo() -> TestClient:
    return tempo._cliente(consulta=MemoriaDeTempo(tempo._copia()))


def _marcas() -> TestClient:
    return marcas._cliente(consulta=MemoriaDeMarcas(marcas._copia()))


def _pede(cliente: TestClient, rota: str, *params: tuple[str, str]) -> Any:
    return cliente.get(rota, params=list(params), headers=AUTORIZACAO)


def _programas(*valores: str) -> list[tuple[str, str]]:
    return [("programa", v) for v in valores]


def test_tempo_de_tela_soma_so_os_programas_marcados_e_devolve_a_lista() -> None:
    cliente = _tempo()

    um = _pede(cliente, tempo.ROTA, *_programas("Fama")).json()
    dois = _pede(cliente, tempo.ROTA, *_programas("Fama", "Jornal")).json()
    todos = _pede(cliente, tempo.ROTA).json()

    assert um["programas"] == ["Fama"] and "programa" not in um
    assert dois["programas"] == ["Fama", "Jornal"]
    (c1,) = um["pessoas"]
    assert c1["tempo_de_tela_ms"] == 1_000  # só j2
    assert dois["pessoas"] == todos["pessoas"]
    assert todos["programas"] == []


def test_marcas_soma_so_os_programas_marcados_e_devolve_a_lista() -> None:
    cliente = _marcas()

    um = _pede(cliente, marcas.ROTA, *_programas("Fama")).json()
    dois = _pede(cliente, marcas.ROTA, *_programas("Fama", "Jornal")).json()
    todos = _pede(cliente, marcas.ROTA).json()

    assert um["programas"] == ["Fama"] and "programa" not in um
    (ambev,) = um["marcas"]
    assert ambev["insercoes"] == 1  # só j2
    assert dois["programas"] == ["Fama", "Jornal"]
    assert dois["marcas"] == todos["marcas"]
    assert todos["programas"] == []


def test_a_pagina_com_limite_devolve_os_programas_nos_dois_relatorios() -> None:
    for cliente, rota in ((_tempo(), tempo.ROTA), (_marcas(), marcas.ROTA)):
        corpo = _pede(cliente, rota, *_programas("Fama"), ("limite", "5")).json()
        assert corpo["programas"] == ["Fama"]


def test_o_detalhe_respeita_os_programas_marcados() -> None:
    videos = _pede(
        _tempo(), f"{tempo.ROTA}/videos", ("pessoa_id", "c1"), *_programas("Fama")
    ).json()
    insercoes = _pede(
        _marcas(), f"{marcas.ROTA}/insercoes", ("marca", "Ambev"), *_programas("Fama")
    ).json()

    assert {v["job_id"] for v in videos} == {"j2"}
    assert {i["job_id"] for i in insercoes} == {"j2"}


def test_o_csv_respeita_os_programas_marcados() -> None:
    so_jornal = _pede(
        _marcas(), marcas.ROTA, *_programas("Jornal"), ("formato", "csv")
    ).text
    so_fama = _pede(
        _marcas(), marcas.ROTA, *_programas("Fama"), ("formato", "csv")
    ).text

    assert so_jornal != so_fama
    assert "Ambev" in so_fama


@pytest.mark.parametrize("relatorio", ["tempo", "marcas"])
def test_programa_ignora_vazio_conta_repetido_uma_vez_e_so_vazio_e_todos(
    relatorio: str,
) -> None:
    cliente, rota = (
        (_tempo(), tempo.ROTA) if relatorio == "tempo" else (_marcas(), marcas.ROTA)
    )

    meio = _pede(cliente, rota, *_programas("", "Fama")).json()
    repetido = _pede(cliente, rota, *_programas("Fama", "Fama")).json()
    so_vazios = _pede(cliente, rota, *_programas("", "")).json()
    sem = _pede(cliente, rota).json()

    assert meio["programas"] == ["Fama"] == repetido["programas"]
    assert meio == repetido
    assert so_vazios == sem
    assert so_vazios["programas"] == []


def test_programa_longo_ou_lista_grande_demais_e_422_nas_oito_rotas() -> None:
    longo = _programas("a" * 101)
    grande = _programas(*(f"p{i}" for i in range(201)))
    ok = _programas(*(f"p{i}" for i in range(200)))
    # Repetidos contam uma vez: 202 valores de 2 programas não estouram a lista.
    repetidos = _programas(*(["Fama", "Jornal"] * 101))

    for cliente, rotas in ((_tempo(), ROTAS_DO_TEMPO), (_marcas(), ROTAS_DAS_MARCAS)):
        for rota, extra in rotas:
            assert _pede(cliente, rota, *longo, *extra).status_code == 422, rota
            assert _pede(cliente, rota, *grande, *extra).status_code == 422, rota
            assert _pede(cliente, rota, *ok, *extra).status_code == 200, rota
            assert _pede(cliente, rota, *repetidos, *extra).status_code == 200, rota


def test_programa_com_caractere_de_controle_e_422() -> None:
    for cliente, rota in ((_tempo(), tempo.ROTA), (_marcas(), marcas.ROTA)):
        assert _pede(cliente, rota, *_programas("a\x00b")).status_code == 422


@pytest.mark.parametrize("relatorio", ["tempo", "marcas"])
def test_bigquery_com_varios_programas_leva_um_parametro_de_array(
    relatorio: str,
) -> None:
    transporte: Any = (tempo if relatorio == "tempo" else marcas).Transporte(
        {"jobComplete": True}
    )
    if relatorio == "tempo":
        BigQueryDeTempo(tempo.CONFIG, transporte).somas(("Fama", "Jornal"), None, None)
    else:
        BigQueryDeMarcas(marcas.CONFIG, transporte).somas(
            ("Fama", "Jornal"), None, None, ()
        )

    (corpo,) = transporte.corpos
    assert "t.programa IN UNNEST(@programas)" in corpo["query"]
    p = {q["name"]: q for q in corpo["queryParameters"]}["programas"]
    assert p["parameterType"] == {"type": "ARRAY", "arrayType": {"type": "STRING"}}
    assert p["parameterValue"] == {
        "arrayValues": [{"value": "Fama"}, {"value": "Jornal"}]
    }
    assert "Fama" not in corpo["query"]
