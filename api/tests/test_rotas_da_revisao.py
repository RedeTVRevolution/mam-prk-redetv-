"""As rotas do tempo de revisão (#251)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from api.auth import Usuario
from api.chaves import (
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.revisao import RepositorioDeRevisaoEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_escopos import MAC
from api.tests.test_passadas import AUTORIZACAO, _job

BASE = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
PULSO = "/v1/jobs/j1/revisao/pulso"
TOTAL = "/v1/jobs/j1/revisao"
OUTRA = {"Authorization": "Bearer token-outra"}


class Relogio:
    def __init__(self) -> None:
        self.agora = BASE

    def __call__(self) -> datetime:
        return self.agora

    def passar(self, segundos: float) -> None:
        self.agora += timedelta(seconds=segundos)


def _cliente(
    papeis: dict[str, list[Papel]], relogio: Relogio | None = None
) -> tuple[TestClient, Relogio]:
    relogio = relogio or Relogio()
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job().model_copy(update={"duracao_s": 3600.0}))
    repo_papeis = RepositorioDePapeisEmMemoria()
    for uid, lista in papeis.items():
        repo_papeis.salvar(uid, lista)
    cliente = TestClient(
        criar_app(
            VerificadorFalso(
                {
                    "token-bom": Usuario(uid="u1", email="a@redetv.com.br"),
                    "token-outra": Usuario(uid="u2", email="b@redetv.com.br"),
                }
            ),
            jobs,
            papeis=repo_papeis,
            revisao=RepositorioDeRevisaoEmMemoria(),
            relogio=relogio,
        )
    )
    return cliente, relogio


def _pulsar(cliente: TestClient, evento: str, headers: Any = AUTORIZACAO) -> int:
    return cliente.post(PULSO, json={"evento": evento}, headers=headers).status_code


def test_pulsos_da_pessoa_viram_minutos_por_hora_de_video() -> None:
    cliente, relogio = _cliente({"u1": ["editor"], "u2": ["curador"]})
    assert _pulsar(cliente, "inicio") == 204
    for _ in range(3):
        relogio.passar(60)
        assert _pulsar(cliente, "atividade") == 204

    corpo = cliente.get(TOTAL, headers=OUTRA).json()

    assert corpo["duracao_s"] == 3600.0
    assert corpo["total_ativo_s"] == 180
    assert corpo["minutos_por_hora_de_video"] == 3.0
    assert corpo["pessoas"] == [
        {
            "uid": "u1",
            "email": "a@redetv.com.br",
            "ativo_s": 180,
            "minutos": 3.0,
            "sessoes": 1,
            "minutos_por_hora_de_video": 3.0,
        }
    ]


def test_cada_pessoa_tem_o_seu_total() -> None:
    cliente, relogio = _cliente({"u1": ["editor"], "u2": ["curador"]})
    _pulsar(cliente, "inicio")
    _pulsar(cliente, "inicio", OUTRA)
    relogio.passar(120)
    _pulsar(cliente, "fim")
    _pulsar(cliente, "fim", OUTRA)

    corpo = cliente.get(TOTAL, headers=OUTRA).json()

    assert [(p["email"], p["ativo_s"]) for p in corpo["pessoas"]] == [
        ("a@redetv.com.br", 120),
        ("b@redetv.com.br", 120),
    ]
    assert corpo["total_ativo_s"] == 240


def test_pulso_exige_decupagem_editar() -> None:
    cliente, _ = _cliente({"u1": ["consulta"]})

    assert _pulsar(cliente, "inicio") == 403


def test_pulso_de_job_que_nao_existe_e_404() -> None:
    cliente, _ = _cliente({"u1": ["editor"]})

    resposta = cliente.post(
        "/v1/jobs/nada/revisao/pulso", json={"evento": "inicio"}, headers=AUTORIZACAO
    )

    assert resposta.status_code == 404


def test_pulso_com_evento_desconhecido_e_422() -> None:
    cliente, _ = _cliente({"u1": ["editor"]})

    assert _pulsar(cliente, "dormir") == 422


def test_total_exige_aprovar_ou_auditoria_ver() -> None:
    cliente, _ = _cliente({"u1": ["editor"], "u2": ["curador"]})

    assert cliente.get(TOTAL, headers=AUTORIZACAO).status_code == 403
    assert cliente.get(TOTAL, headers=OUTRA).status_code == 200


def test_o_administrador_enxerga_pela_auditoria() -> None:
    cliente, _ = _cliente({"u1": ["editor"], "u2": ["administrador"]})

    assert cliente.get(TOTAL, headers=OUTRA).status_code == 200


def test_total_sem_pulsos_e_vazio_e_de_job_que_nao_existe_e_404() -> None:
    cliente, _ = _cliente({"u2": ["curador"]})

    vazio = cliente.get(TOTAL, headers=OUTRA).json()
    ausente = cliente.get("/v1/jobs/nada/revisao", headers=OUTRA)

    assert vazio["pessoas"] == []
    assert vazio["total_ativo_s"] == 0
    assert ausente.status_code == 404


def test_chave_de_sistema_nao_pulsa_nem_consulta() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    emitida = emitir_chave("Playout", frozenset({"ler"}), MAC, chaves, BASE)
    cliente = TestClient(
        criar_app(
            VerificadorFalso({}),
            RepositorioEmMemoria(),
            chaves=VerificadorDeChaveDeApi(chaves, MAC),
        )
    )
    cabecalho = {"X-API-Key": emitida.chave}

    assert (
        cliente.post(PULSO, json={"evento": "inicio"}, headers=cabecalho).status_code
        == 403
    )
    assert cliente.get(TOTAL, headers=cabecalho).status_code == 403
