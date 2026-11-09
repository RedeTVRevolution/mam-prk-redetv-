from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.chaves import (
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.jobs import Job, RepositorioEmMemoria, ServicoIndisponivel
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.programas import Programa, ProgramasEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_escopos import MAC

AGORA = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
AUTORIZACAO = {"Authorization": "Bearer token-bom"}
ROTA = "/v1/jobs/j1"


class DisparoContado:
    def __init__(self, falha: bool = False) -> None:
        self.ids: list[str] = []
        self.falha = falha

    def iniciar(self, job_id: str) -> None:
        if self.falha:
            raise ServicoIndisponivel
        self.ids.append(job_id)


def _job(estado: str = "concluido", **extra: Any) -> Job:
    campos: dict[str, Any] = {
        "id": "j1",
        "nome": "a.mp4",
        "tamanho_bytes": 10,
        "estado": estado,
        "criado_por": "u1",
        "criado_em": AGORA,
        "atualizado_em": AGORA,
        "programa": "TV Fama",
        "data_exibicao": date(2025, 12, 30),
        "versao_pedida": 1,
        "versao_indexada": 1,
    }
    campos.update(extra)
    return Job(**campos)


class Mundo:
    def __init__(
        self,
        job: Job | None = None,
        papeis: Sequence[Papel] = ("editor",),
        disparo: DisparoContado | None = None,
    ) -> None:
        self.jobs = RepositorioEmMemoria()
        self.jobs.salvar(job or _job())
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        self.disparo = disparo or DisparoContado()
        repo_papeis = RepositorioDePapeisEmMemoria()
        repo_papeis.salvar("u1", list(papeis))
        chaves = RepositorioDeChavesEmMemoria()
        self.chave = emitir_chave(
            "Playout", frozenset({"criar", "ler"}), MAC, chaves, AGORA
        ).chave
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {"token-bom": Usuario(uid="u1", email="Ana@redetv.com")}
                ),
                self.jobs,
                chaves=VerificadorDeChaveDeApi(chaves, MAC),
                papeis=repo_papeis,
                auditoria=self.auditoria,
                programas=ProgramasEmMemoria(
                    [
                        Programa(id="tv-fama", nome="TV Fama"),
                        Programa(id="hoje", nome="Hoje em Dia"),
                    ]
                ),
                disparo_da_indexacao=self.disparo,
                relogio=lambda: AGORA,
            ),
            raise_server_exceptions=False,
        )

    def editar(self, corpo: Any) -> Any:
        return self.cliente.patch(ROTA, json=corpo, headers=AUTORIZACAO)

    def job(self) -> Job:
        job = self.jobs.obter("j1")
        assert job is not None
        return job


def test_data_nova_recalcula_o_mes_pede_a_indexacao_e_audita() -> None:
    mundo = Mundo(_job(data_exibicao=None))

    resposta = mundo.editar({"data_exibicao": "2026-11-05"})

    assert resposta.status_code == 200
    assert resposta.json()["data_exibicao"] == "2026-11-05"
    job = mundo.job()
    assert (job.data_exibicao, job.mes_exibicao) == (date(2026, 11, 5), "2026-11")
    assert job.programa == "TV Fama"
    assert job.versao_pedida == 2
    assert job.indexacao is not None and job.indexacao.estado == "pendente"
    assert mundo.disparo.ids == ["j1"]
    [registro] = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert registro.acao == "video.editado"
    assert (registro.alvo_tipo, registro.alvo_id) == ("job", "j1")
    assert registro.email == "ana@redetv.com"
    assert registro.detalhes == {
        "antes": {"data_exibicao": None},
        "depois": {"data_exibicao": "2026-11-05"},
    }


def test_troca_de_ano_e_de_programa_juntas() -> None:
    mundo = Mundo()

    resposta = mundo.editar({"data_exibicao": "2026-01-02", "programa": "Hoje em Dia"})

    assert resposta.status_code == 200
    job = mundo.job()
    assert (job.programa, job.mes_exibicao) == ("Hoje em Dia", "2026-01")
    [registro] = mundo.auditoria.consultar(FiltroDeAuditoria()).registros
    assert registro.detalhes == {
        "antes": {"data_exibicao": "2025-12-30", "programa": "TV Fama"},
        "depois": {"data_exibicao": "2026-01-02", "programa": "Hoje em Dia"},
    }


def test_sem_mudanca_nada_e_pedido_nem_auditado() -> None:
    mundo = Mundo()

    resposta = mundo.editar({"data_exibicao": "2025-12-30", "programa": "TV Fama"})

    assert resposta.status_code == 200
    assert mundo.job().versao_pedida == 1
    assert mundo.disparo.ids == []
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


@pytest.mark.parametrize(
    "corpo",
    [
        {"data_exibicao": "2026-11-10"},  # futura (hoje é 09/11 no fuso da emissora)
        {"data_exibicao": "09/11/2026"},
        {"data_exibicao": 20261105},
        {"programa": "Inexistente"},
        {},
        {"nome": "outro.mp4"},
    ],
)
def test_corpo_invalido_da_422_sem_mexer_no_job(corpo: dict[str, Any]) -> None:
    mundo = Mundo()

    assert mundo.editar(corpo).status_code == 422
    assert mundo.job() == _job()
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_job_que_nao_concluiu_da_409() -> None:
    mundo = Mundo(_job("analisando"))

    assert mundo.editar({"programa": "Hoje em Dia"}).status_code == 409


def test_job_inexistente_da_404() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.patch(
        "/v1/jobs/nao-existe", json={"programa": "Hoje em Dia"}, headers=AUTORIZACAO
    )

    assert resposta.status_code == 404


def test_sem_a_permissao_da_403() -> None:
    mundo = Mundo(papeis=("consulta",))

    assert mundo.editar({"programa": "Hoje em Dia"}).status_code == 403
    assert mundo.job().programa == "TV Fama"


def test_chave_de_sistema_nao_edita() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.patch(
        ROTA, json={"programa": "Hoje em Dia"}, headers={"X-API-Key": mundo.chave}
    )

    assert resposta.status_code == 403


def test_disparo_que_falha_da_503_e_devolve_a_indexacao() -> None:
    mundo = Mundo(disparo=DisparoContado(falha=True))
    antes = mundo.job().indexacao

    resposta = mundo.editar({"programa": "Hoje em Dia"})

    assert resposta.status_code == 503
    assert mundo.job().indexacao == antes
    assert mundo.job().programa == "Hoje em Dia"
