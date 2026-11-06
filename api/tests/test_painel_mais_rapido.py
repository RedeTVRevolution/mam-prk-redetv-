"""As leituras do painel em paralelo, o cache dos e-mails e o corpo da consulta."""

import threading
from collections.abc import Callable
from typing import Any

import pytest

from api.auditoria import RegistroDeAuditoria
from api.painel import EmailsDasContas
from api.relatorios import em_paralelo, linhas_da_consulta
from api.resumos_de_uso import ResumosEmMemoria
from api.tests.test_rotas_do_painel import LINHAS, USO, Mundo
from api.usuarios import ContaDoIdentityPlatform, ContasDeUsuarioEmMemoria

# --- jobCreationMode ---------------------------------------------------------------------


def test_o_corpo_da_consulta_pede_o_job_so_se_precisar() -> None:
    corpos: list[dict[str, Any]] = []

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        corpos.append(corpo)
        return {"jobComplete": True}

    linhas_da_consulta(transporte, "regiao", "SELECT 1")

    assert corpos[0]["jobCreationMode"] == "JOB_CREATION_OPTIONAL"


def test_resposta_sem_job_e_sem_pagina_devolve_as_linhas() -> None:
    resposta = {"jobComplete": True, "rows": [{"f": [{"v": "a"}]}], "queryId": "q"}

    assert linhas_da_consulta(lambda _: resposta, "regiao", "SELECT 1") == [["a"]]


# --- em_paralelo -------------------------------------------------------------------------


def test_em_paralelo_devolve_na_ordem_e_roda_ao_mesmo_tempo() -> None:
    encontro = threading.Barrier(2, timeout=5)  # em série, a primeira esperaria em vão

    def a() -> str:
        encontro.wait()
        return "a"

    def b() -> str:
        encontro.wait()
        return "b"

    assert em_paralelo(a, b) == ("a", "b")


def test_em_paralelo_propaga_o_erro_da_primeira_que_falhou_na_lista() -> None:
    def falha(msg: str) -> Callable[[], None]:
        def chamar() -> None:
            raise RuntimeError(msg)

        return chamar

    with pytest.raises(RuntimeError, match="primeira"):
        em_paralelo(lambda: 1, falha("primeira"), falha("segunda"))


# --- cache dos e-mails -------------------------------------------------------------------


class ContasQueContam(ContasDeUsuarioEmMemoria):
    def __init__(self) -> None:
        super().__init__(
            [ContaDoIdentityPlatform(uid="bia", email="bia@redetv.com.br")]
        )
        self.listagens = 0
        self.falha = False

    def listar(self) -> list[ContaDoIdentityPlatform]:
        self.listagens += 1
        if self.falha:
            raise RuntimeError("Identity Platform fora")
        return super().listar()


def test_emails_nao_listam_de_novo_dentro_do_ttl_e_listam_depois() -> None:
    contas, agora = ContasQueContam(), [100.0]
    emails = EmailsDasContas(contas, validade=60, relogio=lambda: agora[0])

    assert emails() == {"bia": "bia@redetv.com.br"}
    agora[0] = 159.9
    emails()
    assert contas.listagens == 1

    agora[0] = 160.0
    emails()
    assert contas.listagens == 2


def test_emails_com_falha_vazio_e_nao_fica_guardado() -> None:
    contas = ContasQueContam()
    emails = EmailsDasContas(contas, relogio=lambda: 0.0)
    contas.falha = True

    assert emails() == {}

    contas.falha = False
    assert emails() == {"bia": "bia@redetv.com.br"}
    assert contas.listagens == 2


# --- as rotas ----------------------------------------------------------------------------


class ResumosQueFalham(ResumosEmMemoria):
    def __init__(self, onde: str) -> None:
        super().__init__(LINHAS, ["Hoje"], USO)
        self.onde = onde

    def _quebra(self, onde: str) -> None:
        if onde == self.onde:
            raise RuntimeError(f"{onde} fora")

    def programas(self) -> list[str]:
        self._quebra("programas")
        return super().programas()

    def usuarios(self) -> list[str]:
        self._quebra("usuarios")
        return super().usuarios()

    def uso_por_programa(self, *a: Any, **k: Any) -> Any:
        self._quebra("uso_por_programa")
        return super().uso_por_programa(*a, **k)

    def chamadas(self, *a: Any, **k: Any) -> Any:
        self._quebra("chamadas")
        return super().chamadas(*a, **k)


@pytest.mark.parametrize(
    ("rota", "onde"),
    [
        ("/filtros", "programas"),
        ("/filtros", "usuarios"),
        ("/videos", "uso_por_programa"),
        ("/api", "chamadas"),
    ],
)
def test_erro_de_uma_leitura_em_paralelo_continua_503(rota: str, onde: str) -> None:
    mundo = Mundo(["diretoria"], resumos=ResumosQueFalham(onde))

    assert mundo.get(rota).status_code == 503


def test_filtros_sem_a_lista_de_contas_seguem_so_com_o_uid() -> None:
    mundo = Mundo(["diretoria"])

    def fora() -> list[ContaDoIdentityPlatform]:
        raise RuntimeError("fora")

    mundo.contas.listar = fora  # type: ignore[method-assign]

    r = mundo.get("/filtros")

    assert r.status_code == 200
    assert {u["email"] for u in r.json()["usuarios"]} == {None}


@pytest.mark.parametrize(
    ("rota", "params"),
    [
        ("/videos", {}),
        ("/videos", {"formato": "csv"}),
        ("/api", {}),
        ("/api", {"formato": "csv"}),
    ],
)
def test_sem_gravar_a_auditoria_a_requisicao_falha(
    rota: str, params: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    mundo = Mundo(["diretoria"])

    def nao_grava(_: RegistroDeAuditoria) -> None:
        raise RuntimeError("Firestore fora")

    monkeypatch.setattr(mundo.auditoria, "acrescentar", nao_grava)

    assert mundo.get(rota, **params).status_code == 503
