"""O envelope de todo DML do BigQuery (#769): espera, cancela no prazo e confere o erro."""

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

import api.copia_bigquery as modulo
from api.copia_bigquery import (
    ConfigDoBigQuery,
    CopiaBigQuery,
    PrazoDoDml,
    executar_dml,
    parametro,
)
from api.dados_da_purga import executar as executar_purga
from api.jobs_do_painel import ConfigDaTabelaDeJobs, TabelaBigQuery
from api.revisao_do_painel import ConfigDaRevisao, TabelaDaRevisaoBigQuery
from api.taxa_diaria import TabelaDaTaxaBigQuery
from api.tipos_da_taxa import ConfigDaTaxa

REFERENCIA = {"projectId": "p", "jobId": "merge"}
PRAZO = PrazoDoDml(timeout_ms=1_000, cancelar_s=20, desistir_s=60)


class Mundo:
    """Transporte e relógio falsos: cada `sleep` avança o relógio em `passo` segundos."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        estados: Callable[[int], dict[str, Any]],
        passo: int = 5,
        primeira: dict[str, Any] | None = None,
    ) -> None:
        self.segundos = 0
        self.corpos: list[dict[str, Any]] = []
        self.cancelamentos: list[int] = []
        self.falhas_no_cancelamento = 0
        # Quando ligado, cada chamada de acompanhamento demora o que o transporte deixa
        # (`limite_s`, ou 150 s), e o cancelamento demora `duracao_do_cancelamento`.
        self.consome_o_limite = False
        self.duracao_do_cancelamento = 0
        self.fins: list[float] = []
        self._estados = estados
        self._passo = passo
        self._primeira = primeira or {
            "jobComplete": False,
            "jobReference": REFERENCIA,
        }
        monkeypatch.setattr(modulo, "monotonic", lambda: self.segundos)
        monkeypatch.setattr(modulo, "sleep", self._dormir)

    def _dormir(self, tempo: float) -> None:
        self.segundos += self._passo

    def transporte(self, corpo: dict[str, Any]) -> dict[str, Any]:
        self.corpos.append(corpo)
        if "query" in corpo:
            return self._primeira
        if self.consome_o_limite:
            self.segundos += (
                self.duracao_do_cancelamento
                if corpo.get("cancelar")
                else corpo.get("limite_s", 150)
            )
            self.fins.append(self.segundos)
        if corpo.get("cancelar"):
            self.cancelamentos.append(self.segundos)
            if self.falhas_no_cancelamento:
                self.falhas_no_cancelamento -= 1
                raise ConnectionError("cancelamento não confirmado")
            return {}
        return {"status": self._estados(self.segundos)}

    def chamadas_de_acompanhamento(self) -> list[dict[str, Any]]:
        return [c for c in self.corpos if "jobReference" in c]


def _executar(mundo: Mundo, prazo: PrazoDoDml = PRAZO) -> dict[str, Any]:
    return executar_dml(
        mundo.transporte,
        "regiao-x",
        "MERGE x",
        [parametro("a", "1")],
        prazo,
        descricao="a carga",
    )


def _sempre(estado: str, **resto: Any) -> Callable[[int], dict[str, Any]]:
    return lambda _s: {"state": estado, **resto}


def test_termina_na_primeira_resposta_e_devolve_ela(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mundo = Mundo(
        monkeypatch,
        _sempre("RUNNING"),
        primeira={"jobComplete": True, "numDmlAffectedRows": "3"},
    )

    resposta = _executar(mundo)

    assert resposta["numDmlAffectedRows"] == "3"
    assert mundo.corpos == [
        {
            "query": "MERGE x",
            "useLegacySql": False,
            "location": "regiao-x",
            "timeoutMs": 1_000,
            "queryParameters": [parametro("a", "1")],
        }
    ]


def test_termina_depois_de_consultas_de_estado(monkeypatch: pytest.MonkeyPatch) -> None:
    mundo = Mundo(monkeypatch, lambda s: {"state": "DONE" if s >= 10 else "RUNNING"})

    _executar(mundo)

    assert len(mundo.chamadas_de_acompanhamento()) == 3
    assert mundo.cancelamentos == []
    assert mundo.chamadas_de_acompanhamento()[0]["jobReference"] == {
        "location": "regiao-x",
        **REFERENCIA,
    }


def test_cancela_uma_vez_ao_passar_o_prazo_e_espera_o_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mundo = Mundo(monkeypatch, lambda s: {"state": "DONE" if s >= 40 else "RUNNING"})

    _executar(mundo)

    assert mundo.cancelamentos == [20]


def test_falha_ao_cancelar_vai_ao_log_e_a_espera_segue(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    mundo = Mundo(monkeypatch, lambda s: {"state": "DONE" if s >= 40 else "RUNNING"})
    mundo.falhas_no_cancelamento = 1

    with caplog.at_level(logging.ERROR):
        _executar(mundo)

    assert mundo.cancelamentos == [20, 25]
    assert "cancelamento" in caplog.text


def test_error_result_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    mundo = Mundo(monkeypatch, _sempre("DONE", errorResult={"reason": "invalidQuery"}))

    with pytest.raises(RuntimeError, match="a carga falhou.*invalidQuery"):
        _executar(mundo)


def test_desiste_no_limite_sem_prova_de_que_parou(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mundo = Mundo(monkeypatch, _sempre("RUNNING"))

    with pytest.raises(RuntimeError, match="a carga não terminou no prazo"):
        _executar(mundo)

    assert mundo.segundos == 60
    assert mundo.cancelamentos == [20]


def test_sem_referencia_do_job_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    mundo = Mundo(monkeypatch, _sempre("DONE"), primeira={"jobComplete": False})

    with pytest.raises(RuntimeError, match="a carga"):
        _executar(mundo)


def test_no_prazo_curto_o_cancelamento_chega_antes_da_desistencia_e_cabe_na_janela(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.copia_bigquery import PRAZO_CURTO

    # O relógio salta de 0 para bem depois da desistência: o cancelamento sai mesmo assim.
    mundo = Mundo(monkeypatch, _sempre("RUNNING"), passo=10_000)

    with pytest.raises(RuntimeError, match="não terminou no prazo"):
        _executar(mundo, PRAZO_CURTO)

    assert mundo.cancelamentos == [10_000]

    # Com o relógio andando de 5 em 5 s, nenhuma chamada passa do que falta.
    mundo = Mundo(monkeypatch, _sempre("RUNNING"))
    with pytest.raises(RuntimeError):
        _executar(mundo, PRAZO_CURTO)

    assert mundo.cancelamentos[0] == PRAZO_CURTO.cancelar_s
    assert mundo.segundos <= PRAZO_CURTO.desistir_s + 5
    assert PRAZO_CURTO.desistir_s > PRAZO_CURTO.cancelar_s
    for chamada in mundo.chamadas_de_acompanhamento():
        assert 0 < chamada["limite_s"] <= 150


def test_cada_modulo_cancela_quando_o_job_nao_termina(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chamadores: dict[str, Callable[[Callable[..., Any]], object]] = {
        "copia": lambda t: CopiaBigQuery(
            ConfigDoBigQuery("p", "d", "t", "r"), t
        ).gravar("j1", []),
        "jobs": lambda t: TabelaBigQuery(
            ConfigDaTabelaDeJobs("p", "d", "t", "r"), t
        ).gravar([]),
        "revisao": lambda t: TabelaDaRevisaoBigQuery(
            ConfigDaRevisao("p", "d", "r", "t1", "t2"), t
        ).gravar([]),
        "taxa": lambda t: TabelaDaTaxaBigQuery(
            ConfigDaTaxa("p", "d", "r", "t"), t
        ).substituir([date(2026, 1, 1)], []),
        "purga": lambda t: executar_purga(
            ConfigDoBigQuery("p", "d", "t", "r"), t, "DELETE x", "j1"
        ),
    }
    for nome, chamar in chamadores.items():
        mundo = Mundo(monkeypatch, _sempre("RUNNING"))
        with pytest.raises(RuntimeError):
            chamar(mundo.transporte)
        assert mundo.cancelamentos, nome


def test_a_purga_com_errors_levanta_e_devolve_as_linhas_afetadas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ConfigDoBigQuery("p", "d", "t", "r")
    erro = Mundo(
        monkeypatch,
        _sempre("DONE"),
        primeira={"jobComplete": True, "errors": [{"reason": "invalidQuery"}]},
    )
    with pytest.raises(RuntimeError):
        executar_purga(config, erro.transporte, "DELETE x", "j1")

    bom = Mundo(
        monkeypatch,
        _sempre("DONE"),
        primeira={"jobComplete": True, "numDmlAffectedRows": "7"},
    )
    assert executar_purga(config, bom.transporte, "DELETE x", "j1") == 7


def test_a_consulta_antes_do_marco_nao_empurra_o_cancelamento_para_depois_do_teto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.copia_bigquery import PRAZO_CURTO

    mundo = Mundo(monkeypatch, _sempre("RUNNING"))
    mundo.consome_o_limite = True
    with pytest.raises(RuntimeError):
        _executar(mundo, PRAZO_CURTO)

    assert mundo.cancelamentos[0] == PRAZO_CURTO.cancelar_s
    assert max(mundo.fins) <= PRAZO_CURTO.desistir_s


def test_o_relogio_e_relido_depois_de_um_cancelamento_demorado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.copia_bigquery import PRAZO_CURTO

    mundo = Mundo(monkeypatch, _sempre("RUNNING"))
    mundo.consome_o_limite = True
    mundo.duracao_do_cancelamento = 8
    with pytest.raises(RuntimeError):
        _executar(mundo, PRAZO_CURTO)

    assert max(mundo.fins) <= PRAZO_CURTO.desistir_s
    assert mundo.segundos <= PRAZO_CURTO.desistir_s


def test_a_purga_que_nao_termina_diz_nao_confirmada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mundo = Mundo(monkeypatch, _sempre("RUNNING"))
    with pytest.raises(RuntimeError, match="purga de j1 no BigQuery não confirmada"):
        executar_purga(
            ConfigDoBigQuery("p", "d", "t", "r"), mundo.transporte, "DELETE x", "j1"
        )
