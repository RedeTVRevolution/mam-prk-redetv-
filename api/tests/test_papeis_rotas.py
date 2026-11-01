from datetime import UTC, datetime
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, Permissao, RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
NOVO_JOB = {"nome": "a.mp4", "tamanho_bytes": 10, "tipo": "video/mp4"}
AUTORIZACAO = {"Authorization": "Bearer token-bom"}


def _mundo(papeis: list[Papel] | None) -> TestClient:
    repo_papeis = RepositorioDePapeisEmMemoria()
    if papeis is not None:
        repo_papeis.salvar("u1", papeis)
    jobs = RepositorioEmMemoria()
    jobs.salvar(
        Job(
            id="j1",
            nome="a.mp4",
            tamanho_bytes=10,
            estado="concluido",
            criado_por="u1",
            criado_em=BASE,
            atualizado_em=BASE,
        )
    )
    armazenamento = ArmazenamentoFalso()
    armazenamento.decupagens["j1"] = [b"{}"]
    return TestClient(
        criar_app(
            VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
            jobs,
            armazenamento,
            papeis=repo_papeis,
        )
    )


def test_so_consulta_nao_cria_job_mas_le_a_decupagem() -> None:
    cliente = _mundo(["consulta"])

    assert (
        cliente.post("/v1/jobs", json=NOVO_JOB, headers=AUTORIZACAO).status_code == 403
    )
    assert cliente.get("/v1/jobs/j1/decupagem", headers=AUTORIZACAO).status_code == 200


def test_quadro_exige_decupagem_ver() -> None:
    rota = "/v1/jobs/j1/quadros/plano-0.jpg"

    assert _mundo(["consulta"]).get(rota, headers=AUTORIZACAO).status_code == 200
    assert _mundo([]).get(rota, headers=AUTORIZACAO).status_code == 403


@pytest.mark.parametrize("papeis", [None, ["operador"], ["consulta", "operador"]])
def test_quem_envia_cria_job(papeis: list[Papel] | None) -> None:
    resposta = _mundo(papeis).post("/v1/jobs", json=NOVO_JOB, headers=AUTORIZACAO)

    assert resposta.status_code == 202


def test_conta_sem_documento_envia_e_ve_como_na_e0() -> None:
    cliente = _mundo(None)

    assert cliente.get("/v1/jobs", headers=AUTORIZACAO).status_code == 200
    assert cliente.get("/v1/jobs/j1", headers=AUTORIZACAO).status_code == 200
    assert cliente.get("/v1/jobs/j1/reproducao", headers=AUTORIZACAO).status_code == 200
    assert cliente.get("/v1/jobs/j1/decupagem", headers=AUTORIZACAO).status_code == 200


def test_documento_com_lista_vazia_nao_tem_acesso_a_nada() -> None:
    cliente = _mundo([])

    assert cliente.get("/v1/jobs", headers=AUTORIZACAO).status_code == 403
    assert (
        cliente.post("/v1/jobs", json=NOVO_JOB, headers=AUTORIZACAO).status_code == 403
    )
    assert cliente.delete("/v1/jobs/j1", headers=AUTORIZACAO).status_code == 403


def test_editor_nao_envia_video() -> None:
    resposta = _mundo(["editor"]).post("/v1/jobs", json=NOVO_JOB, headers=AUTORIZACAO)

    assert resposta.status_code == 403


def test_sem_token_o_401_vem_antes_do_403() -> None:
    assert _mundo([]).get("/v1/jobs").status_code == 401


def test_health_continua_aberto() -> None:
    assert _mundo([]).get("/v1/health").status_code == 200


def test_eu_devolve_papeis_e_permissoes() -> None:
    resposta = _mundo(["curador"]).get("/v1/eu", headers=AUTORIZACAO)

    assert resposta.json() == {
        "uid": "u1",
        "email": "a@b.c",
        "email_verificado": False,
        "papeis": ["curador"],
        "permissoes": [
            "correcao.aprovar",
            "decupagem.editar",
            "decupagem.ver",
        ],
    }


def test_eu_sem_documento_mostra_os_papeis_padrao() -> None:
    corpo = _mundo(None).get("/v1/eu", headers=AUTORIZACAO).json()

    assert corpo["papeis"] == ["consulta", "operador"]
    assert corpo["permissoes"] == ["decupagem.ver", "video.enviar"]


def _mundo_admin(
    papeis: list[Papel] | None, admins: str | None, verificado: bool = True
) -> TestClient:
    repo_papeis = RepositorioDePapeisEmMemoria()
    if papeis is not None:
        repo_papeis.salvar("u1", papeis)
    jobs = RepositorioEmMemoria()
    return TestClient(
        criar_app(
            VerificadorFalso(
                {
                    "token-bom": Usuario(
                        uid="u1",
                        email=" Ana@RedeTV.com.br",
                        email_verificado=verificado,
                    )
                }
            ),
            jobs,
            ArmazenamentoFalso(),
            papeis=repo_papeis,
            admins_emergencia=admins,
        )
    )


TODAS = sorted(get_args(Permissao))


@pytest.mark.parametrize("guardados", [None, ["consulta"]])
def test_admin_de_emergencia_vira_administrador_com_tudo(
    guardados: list[Papel] | None,
) -> None:
    cliente = _mundo_admin(guardados, "ana@redetv.com.br,outra@x.y")

    eu = cliente.get("/v1/eu", headers=AUTORIZACAO).json()

    assert "administrador" in eu["papeis"]
    assert eu["permissoes"] == TODAS
    assert (
        cliente.post("/v1/jobs", json=NOVO_JOB, headers=AUTORIZACAO).status_code == 202
    )


def test_admin_de_emergencia_passa_nas_rotas_de_editar_e_aprovar() -> None:
    cliente = _mundo_admin(["consulta"], "ana@redetv.com.br")
    comum = _mundo_admin(["consulta"], None)

    for metodo, caminho in (
        ("GET", "/v1/jobs/x/correcoes"),
        ("POST", "/v1/jobs/x/correcoes/y/aprovar"),
    ):
        assert comum.request(metodo, caminho, headers=AUTORIZACAO).status_code == 403
        assert cliente.request(metodo, caminho, headers=AUTORIZACAO).status_code == 404


def test_email_nao_verificado_nao_vira_administrador() -> None:
    cliente = _mundo_admin(["consulta"], "ana@redetv.com.br", verificado=False)

    eu = cliente.get("/v1/eu", headers=AUTORIZACAO).json()

    assert eu["papeis"] == ["consulta"]
    assert (
        cliente.post("/v1/jobs", json=NOVO_JOB, headers=AUTORIZACAO).status_code == 403
    )


def test_sem_lista_de_admins_o_comportamento_e_o_de_hoje() -> None:
    eu = _mundo_admin(None, None).get("/v1/eu", headers=AUTORIZACAO).json()

    assert eu["papeis"] == ["consulta", "operador"]
