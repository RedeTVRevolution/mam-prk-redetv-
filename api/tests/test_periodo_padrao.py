"""O período padrão dos relatórios (#462): os últimos 7 dias, no dia de São Paulo."""

import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from api.auditoria import FiltroDeAuditoria
from api.periodo_padrao import DIAS_DO_PERIODO_PADRAO, periodo_padrao
from api.relatorio_de_marcas import ConsultaEmMemoria as ConsultaDeMarcas
from api.tempo_de_tela import ConsultaEmMemoria
from api.tests.test_passadas import AUTORIZACAO
from api.tests.test_relatorio_de_marcas import _cliente as _cliente_das_marcas
from api.tests.test_relatorio_de_marcas import _copia as _copia_das_marcas
from api.tests.test_rotas_do_painel import Mundo
from api.tests.test_tempo_de_tela import ROTA, _cliente, _copia

# 6 de novembro, 22h em São Paulo: já é dia 7 em UTC, e o padrão ainda é o dia 6.
NOITE_DE_SP = datetime(2026, 11, 7, 1, 0, tzinfo=UTC)
PADRAO = {"desde": "2026-10-31", "ate": "2026-11-06"}


def _tempo_de_tela(**params: str) -> dict[str, Any]:
    cliente = _cliente(
        consulta=ConsultaEmMemoria(_copia()), relogio=lambda: NOITE_DE_SP
    )
    resposta = cliente.get(ROTA, params=params, headers=AUTORIZACAO)
    assert resposta.status_code == 200
    corpo: dict[str, Any] = resposta.json()
    return corpo


def test_o_padrao_e_de_hoje_menos_6_dias_ate_hoje_no_dia_de_sao_paulo() -> None:
    assert periodo_padrao(NOITE_DE_SP) == (date(2026, 10, 31), date(2026, 11, 6))
    assert DIAS_DO_PERIODO_PADRAO == 7


def test_a_web_usa_o_mesmo_numero_de_dias() -> None:
    fonte = (Path(__file__).parents[2] / "web" / "src" / "periodoPadrao.ts").read_text()
    achado = re.search(r"DIAS_DO_PERIODO_PADRAO = (\d+)", fonte)
    assert achado and int(achado.group(1)) == DIAS_DO_PERIODO_PADRAO


def test_tempo_de_tela_sem_periodo_usa_os_ultimos_7_dias() -> None:
    corpo = _tempo_de_tela()

    assert (corpo["desde"], corpo["ate"]) == (PADRAO["desde"], PADRAO["ate"])


def test_tempo_de_tela_aceita_outro_periodo_e_o_historico_inteiro() -> None:
    outro = _tempo_de_tela(desde="2026-10-01", ate="2026-10-31")
    assert (outro["desde"], outro["ate"]) == ("2026-10-01", "2026-10-31")

    inteiro = _tempo_de_tela(desde="", ate="")
    assert (inteiro["desde"], inteiro["ate"]) == (None, None)
    assert inteiro["pessoas"] != []

    so_um = _tempo_de_tela(desde="2026-10-01")
    assert (so_um["desde"], so_um["ate"]) == ("2026-10-01", None)


def test_data_malformada_e_422() -> None:
    cliente = _cliente(
        consulta=ConsultaEmMemoria(_copia()), relogio=lambda: NOITE_DE_SP
    )

    resposta = cliente.get(ROTA, params={"desde": "ontem"}, headers=AUTORIZACAO)

    assert resposta.status_code == 422


def test_marcas_sem_periodo_usa_os_ultimos_7_dias() -> None:
    cliente = _cliente_das_marcas(
        consulta=ConsultaDeMarcas(_copia_das_marcas()), relogio=lambda: NOITE_DE_SP
    )
    rota = "/v1/relatorios/marcas"

    padrao = cliente.get(rota, headers=AUTORIZACAO).json()
    inteiro = cliente.get(
        rota, params={"desde": "", "ate": ""}, headers=AUTORIZACAO
    ).json()

    assert (padrao["desde"], padrao["ate"]) == (PADRAO["desde"], PADRAO["ate"])
    assert (inteiro["desde"], inteiro["ate"]) == (None, None)


def test_painel_sem_periodo_usa_os_ultimos_7_dias_e_a_auditoria_grava_o_periodo() -> (
    None
):
    mundo = Mundo(["diretoria"], relogio=lambda: NOITE_DE_SP, periodo_padrao=True)

    assert mundo.get("/acessos").status_code == 200
    assert mundo.get("/acessos", desde="", ate="").status_code == 200

    abertos = mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.aberto")
    ).registros
    assert sorted((r.detalhes["filtro"] for r in abertos), key=len) == [{}, PADRAO]
