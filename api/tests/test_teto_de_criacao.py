from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient

from api import jobs as modulo_jobs
from api.auth import Escopo, Usuario
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

AGORA = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
MAC = MacSimulado({1: b"k1"}, versao_atual=1)
NOVO_JOB = {
    "nome": "a.mp4",
    "tamanho_bytes": 10,
    "tipo": "video/mp4",
    "data_exibicao": "2026-10-01",
}
PESSOA = {"Authorization": "Bearer token-bom"}
OUTRA_PESSOA = {"Authorization": "Bearer token-outro"}


@pytest.fixture(autouse=True)
def tetos_pequenos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(modulo_jobs, "TETO_POR_HORA_DO_SISTEMA", 3)
    monkeypatch.setattr(modulo_jobs, "TETO_POR_HORA_DA_PESSOA", 2)


class Mundo:
    def __init__(self) -> None:
        self.chaves = RepositorioDeChavesEmMemoria()
        self.jobs = RepositorioEmMemoria()
        self.agora = AGORA
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("u1", ["editor"])
        papeis.salvar("u2", ["editor"])
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "token-bom": Usuario(uid="u1", email="a@b.c"),
                        "token-outro": Usuario(uid="u2", email="d@e.f"),
                    }
                ),
                self.jobs,
                ArmazenamentoFalso(),
                chaves=VerificadorDeChaveDeApi(self.chaves, MAC),
                papeis=papeis,
                relogio=lambda: self.agora,
            )
        )

    def chave(self, sistema: str) -> dict[str, str]:
        escopos = cast(frozenset[Escopo], frozenset({"criar"}))
        return {
            "X-API-Key": emitir_chave(sistema, escopos, MAC, self.chaves, AGORA).chave
        }

    def ja_criados(self, criado_por: str, quantos: int, ha: timedelta) -> None:
        sistema = criado_por.removeprefix("sistema:") if ":" in criado_por else None
        for i in range(quantos):
            self.jobs.salvar(
                Job(
                    id=f"{criado_por}-{ha}-{i}",
                    nome="a.mp4",
                    tamanho_bytes=10,
                    estado="aguardando_upload",
                    criado_por=criado_por,
                    sistema=sistema,
                    criado_em=AGORA - ha,
                    atualizado_em=AGORA - ha,
                )
            )

    def criar(self, headers: dict[str, str]) -> int:
        return self.cliente.post("/v1/jobs", json=NOVO_JOB, headers=headers).status_code


def test_sistema_que_passa_do_teto_recebe_429_com_retry_after() -> None:
    mundo = Mundo()
    chave = mundo.chave("Legado")

    assert [mundo.criar(chave) for _ in range(3)] == [202, 202, 202]
    resposta = mundo.cliente.post("/v1/jobs", json=NOVO_JOB, headers=chave)

    assert resposta.status_code == 429
    assert resposta.headers["Retry-After"] == "3600"
    assert len(mundo.jobs.listar()) == 3


def test_outra_chave_nao_e_afetada_pelo_teto_do_vizinho() -> None:
    mundo = Mundo()
    mundo.ja_criados("sistema:Legado", 3, timedelta(minutes=5))

    assert mundo.criar(mundo.chave("Legado")) == 429
    assert mundo.criar(mundo.chave("Outro")) == 202


def test_pessoa_tambem_tem_teto_e_a_outra_pessoa_segue_livre() -> None:
    mundo = Mundo()

    assert [mundo.criar(PESSOA) for _ in range(3)] == [202, 202, 429]
    assert mundo.criar(OUTRA_PESSOA) == 202


def test_job_criado_ha_mais_de_uma_hora_nao_conta() -> None:
    mundo = Mundo()
    mundo.ja_criados("sistema:Legado", 3, timedelta(hours=1, seconds=1))

    assert mundo.criar(mundo.chave("Legado")) == 202


def test_job_do_sistema_nao_conta_no_teto_de_pessoa() -> None:
    mundo = Mundo()
    mundo.ja_criados("sistema:Legado", 2, timedelta(minutes=1))

    assert mundo.criar(PESSOA) == 202


def test_repeticao_de_job_ja_criado_nao_e_barrada_pelo_teto() -> None:
    mundo = Mundo()
    chave = mundo.chave("Legado")
    ultimo = {**chave, "Idempotency-Key": "ultimo"}

    assert [mundo.criar(chave) for _ in range(2)] == [202, 202]
    assert mundo.criar(ultimo) == 202
    assert mundo.criar(ultimo) == 200
    assert len(mundo.jobs.listar()) == 3


def test_repeticao_barrada_pelo_teto_cria_o_job_depois_da_espera() -> None:
    mundo = Mundo()
    mundo.ja_criados("sistema:Legado", 3, timedelta(minutes=5))
    chave = {**mundo.chave("Legado"), "Idempotency-Key": "barrado"}

    assert mundo.criar(chave) == 429
    assert mundo.criar(chave) == 429
    mundo.agora = AGORA + timedelta(hours=1)
    assert mundo.criar(chave) == 200
    assert len(mundo.jobs.listar()) == 4
