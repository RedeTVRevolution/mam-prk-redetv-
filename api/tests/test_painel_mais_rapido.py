"""As leituras do painel em paralelo, o cache dos e-mails e o corpo da consulta."""

import threading
from collections.abc import Callable
from typing import Any

import pytest

from api.auditoria import RegistroDeAuditoria
from api.custo_do_painel import CustoEmMemoria
from api.painel import EmailsDasContas
from api.qualidade_do_painel import QualidadeEmMemoria
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


def test_falha_nos_emails_vale_10_s_e_guarda_a_ultima_lista() -> None:
    contas, agora = ContasQueContam(), [0.0]
    emails = EmailsDasContas(contas, espera_na_falha=10, relogio=lambda: agora[0])
    contas.falha = True

    assert emails() == {}
    assert emails() == {}  # quem esperava a trava não lista de novo
    assert contas.listagens == 1

    agora[0] = 10.0
    contas.falha = False
    assert emails() == {"bia": "bia@redetv.com.br"}

    agora[0] = 70.0
    contas.falha = True
    assert emails() == {"bia": "bia@redetv.com.br"}  # vale a última lista boa
    assert contas.listagens == 3


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


# --- /revisao e e-mails em paralelo (#775) -----------------------------------------------


class QualidadeQueConta(QualidadeEmMemoria):
    def __init__(self, encontro: threading.Barrier | None = None) -> None:
        super().__init__([], [])
        self.encontro = encontro
        self.taxas = 0

    def taxa_de_correcao(self, *a: Any, **k: Any) -> Any:
        self.taxas += 1
        if self.encontro:
            self.encontro.wait()
        return super().taxa_de_correcao(*a, **k)

    def tempo_de_revisao(self, *a: Any, **k: Any) -> Any:
        if self.encontro:
            self.encontro.wait()
        return super().tempo_de_revisao(*a, **k)


class ResumosComEncontro(ResumosEmMemoria):
    def __init__(self, encontro: threading.Barrier) -> None:
        super().__init__(LINHAS, ["Hoje"], USO)
        self.encontro = encontro

    def correcoes(self, *a: Any, **k: Any) -> Any:
        self.encontro.wait()
        return super().correcoes(*a, **k)


def test_revisao_le_correcoes_taxa_tempo_e_emails_ao_mesmo_tempo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encontro = threading.Barrier(4, timeout=5)  # em série, a primeira esperaria em vão
    mundo = Mundo(
        ["diretoria"],
        resumos=ResumosComEncontro(encontro),
        qualidade=QualidadeQueConta(encontro),
    )
    listar = mundo.contas.listar

    def listar_no_encontro() -> Any:
        encontro.wait()
        return listar()

    monkeypatch.setattr(mundo.contas, "listar", listar_no_encontro)

    assert mundo.get("/revisao").status_code == 200


def test_revisao_com_filtro_de_usuario_nao_le_a_taxa() -> None:
    qualidade = QualidadeQueConta()
    mundo = Mundo(["diretoria"], qualidade=qualidade)

    assert mundo.get("/revisao", usuario="bia").status_code == 200
    assert qualidade.taxas == 0


@pytest.mark.parametrize(
    ("rota", "leitura"),
    [("/acessos", "acessos"), ("/buscas", "uso_por_quem"), ("/custo", "custos")],
)
def test_a_leitura_e_os_emails_frios_andam_ao_mesmo_tempo(
    rota: str, leitura: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    encontro = threading.Barrier(2, timeout=5)  # em série, o primeiro esperaria em vão
    faturamento = CustoEmMemoria([], [])
    mundo = Mundo(["diretoria"], faturamento=faturamento)

    def com_encontro(original: Callable[..., Any]) -> Callable[..., Any]:
        def chamar(*a: Any, **k: Any) -> Any:
            encontro.wait()
            return original(*a, **k)

        return chamar

    monkeypatch.setattr(mundo.contas, "listar", com_encontro(mundo.contas.listar))
    fonte = faturamento if rota == "/custo" else mundo.resumos
    monkeypatch.setattr(fonte, leitura, com_encontro(getattr(fonte, leitura)))

    assert mundo.get(rota).status_code == 200


@pytest.mark.parametrize("rota", ["/buscas", "/videos"])
def test_programa_e_usuario_juntos_dao_422_sem_listar_as_contas(
    rota: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    mundo = Mundo(["diretoria"])
    listagens = 0
    listar = mundo.contas.listar

    def contando() -> Any:
        nonlocal listagens
        listagens += 1
        return listar()

    monkeypatch.setattr(mundo.contas, "listar", contando)

    assert mundo.get(rota, programa="Hoje", usuario="bia").status_code == 422
    assert listagens == 0
