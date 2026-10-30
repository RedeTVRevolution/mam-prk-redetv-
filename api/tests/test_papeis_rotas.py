from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
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
