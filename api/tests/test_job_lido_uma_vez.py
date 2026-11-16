"""Rotas com `{job_id}`: a ordem das respostas (404, 403) e uma leitura de Job por pedido."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auth import Usuario
from api.catalogo import EnvioParaLixeira
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.modelo_do_job import Estado, Job
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
MAC = MacSimulado({1: b"k1"}, versao_atual=1)
ADMIN = {"Authorization": "Bearer admin"}
CURADOR = {"Authorization": "Bearer curador"}
CONSULTA = {"Authorization": "Bearer consulta"}


class RepositorioQueConta(RepositorioEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.leituras: list[str] = []

    def obter(self, job_id: str) -> Job | None:
        self.leituras.append(job_id)
        return super().obter(job_id)


def _job(id: str, estado: Estado = "concluido", **extra: Any) -> Job:
    return Job(
        id=id,
        nome="tv-fama.mp4",
        tamanho_bytes=10,
        sha256="a" * 64,
        estado=estado,
        criado_por="sistema:Playout",
        sistema="Playout",
        criado_em=BASE,
        atualizado_em=BASE,
        duracao_s=60.0,
        **extra,
    )


class Mundo:
    def __init__(self, jobs: RepositorioQueConta | None = None) -> None:
        self.jobs = jobs or RepositorioQueConta()
        self.jobs.salvar(_job("vivo"))
        self.jobs.salvar(_job("andando", "analisando"))
        self.jobs.salvar(
            _job(
                "lixo",
                lixeira=EnvioParaLixeira(
                    em=BASE, por_uid="adm", por_email="a@x.com", motivo="m"
                ),
            )
        )
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("adm", ["administrador"])
        papeis.salvar("cur", ["curador"])
        papeis.salvar("con", ["consulta"])
        chaves = RepositorioDeChavesEmMemoria()
        self.chave = {
            "X-API-Key": emitir_chave(
                "Playout", frozenset({"criar", "ler", "cancelar"}), MAC, chaves, BASE
            ).chave
        }
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "admin": Usuario(uid="adm", email="ana@redetv.com"),
                        "curador": Usuario(uid="cur", email="cur@redetv.com"),
                        "consulta": Usuario(uid="con", email="con@redetv.com"),
                    }
                ),
                self.jobs,
                ArmazenamentoFalso(),
                chaves=VerificadorDeChaveDeApi(chaves, MAC),
                papeis=papeis,
                relogio=lambda: BASE,
            )
        )

    def pedir(self, metodo: str, rota: str, quem: dict[str, str]) -> int:
        resto = rota.removeprefix("/v1/jobs/").partition("/")[2]
        corpo = CORPOS.get((metodo, resto), {})
        return self.cliente.request(
            metodo, rota, headers=quem, json=corpo or None
        ).status_code


_MOTIVO = {"motivo": "x"}
CORPOS: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "correcoes"): {
        "tipo": "plano.limpo",
        "item_id": "x",
        "valor": "true",
        "motivo": "x",
        "versao": "v",
    },
    ("POST", "correcoes/c1/desfazer"): _MOTIVO,
    ("POST", "correcoes/c1/recusar"): _MOTIVO,
    ("POST", "fila/c1/descartar"): _MOTIVO,
    ("POST", "fila/c1/reaplicar"): {**_MOTIVO, "item_id": "i"},
    ("PATCH", ""): {"programa": "TV Fama"},
    ("POST", "revisao/pulso"): {"evento": "inicio"},
}


# (método, rota com {j}, quem passa em permissão): `quem` é quem tem a permissão da rota.
ROTAS = [
    ("GET", "/v1/jobs/{j}", "chave"),
    ("DELETE", "/v1/jobs/{j}", "chave"),
    ("GET", "/v1/jobs/{j}/reproducao", "chave"),
    ("GET", "/v1/jobs/{j}/download", "chave"),
    ("GET", "/v1/jobs/{j}/decupagem", "chave"),
    ("GET", "/v1/jobs/{j}/decupagem/download", "chave"),
    ("GET", "/v1/jobs/{j}/quadros/plano-1.jpg", "chave"),
    ("GET", "/v1/jobs/{j}/passadas", "chave"),
    ("GET", "/v1/jobs/{j}/passadas/p1", "chave"),
    ("GET", "/v1/jobs/{j}/passadas/p1/comparacao", "chave"),
    ("GET", "/v1/jobs/{j}/correcoes", "curador"),
    ("POST", "/v1/jobs/{j}/correcoes", "curador"),
    ("POST", "/v1/jobs/{j}/correcoes/c1/desfazer", "curador"),
    ("POST", "/v1/jobs/{j}/correcoes/c1/aprovar", "curador"),
    ("POST", "/v1/jobs/{j}/correcoes/c1/recusar", "curador"),
    ("POST", "/v1/jobs/{j}/revisao/aprovar", "curador"),
    ("GET", "/v1/jobs/{j}/fila", "curador"),
    ("POST", "/v1/jobs/{j}/fila/c1/reaplicar", "curador"),
    ("POST", "/v1/jobs/{j}/fila/c1/descartar", "curador"),
    ("PATCH", "/v1/jobs/{j}", "curador"),
    ("POST", "/v1/jobs/{j}/revisao/pulso", "curador"),
    ("GET", "/v1/jobs/{j}/revisao", "curador"),
]


def _quem(mundo: Mundo, quem: str) -> dict[str, str]:
    return mundo.chave if quem == "chave" else CURADOR


@pytest.mark.parametrize(("metodo", "rota", "quem"), ROTAS)
def test_ausente_e_lixeira_dao_404_e_sem_permissao_dao_403(
    metodo: str, rota: str, quem: str
) -> None:
    mundo = Mundo()
    com_permissao = _quem(mundo, quem)
    # Quem tem a permissão: Job ausente ou na lixeira (sem ser Administrador) é 404.
    assert mundo.pedir(metodo, rota.format(j="nao-existe"), com_permissao) == 404
    assert mundo.pedir(metodo, rota.format(j="lixo"), com_permissao) == 404
    # Quem não tem: 403 antes do 404 de Job ausente; na lixeira o 404 vem primeiro.
    sem_permissao = CONSULTA if quem == "curador" else {"X-API-Key": "chave-ruim"}
    esperado_ausente = 403 if quem == "curador" else 401
    assert (
        mundo.pedir(metodo, rota.format(j="nao-existe"), sem_permissao)
        == esperado_ausente
    )
    if quem == "curador":
        assert mundo.pedir(metodo, rota.format(j="vivo"), sem_permissao) == 403
        assert mundo.pedir(metodo, rota.format(j="lixo"), sem_permissao) == 404


@pytest.mark.parametrize(
    ("metodo", "rota", "quem", "job"),
    [
        ("GET", "/v1/jobs/{j}", "chave", "vivo"),
        ("DELETE", "/v1/jobs/{j}", "chave", "andando"),
        ("GET", "/v1/jobs/{j}/reproducao", "chave", "vivo"),
        ("GET", "/v1/jobs/{j}/download", "chave", "vivo"),
        ("GET", "/v1/jobs/{j}/quadros/plano-1.jpg", "chave", "vivo"),
        ("GET", "/v1/jobs/{j}/passadas", "chave", "vivo"),
        ("GET", "/v1/jobs/{j}/correcoes", "curador", "vivo"),
        ("PATCH", "/v1/jobs/{j}", "curador", "vivo"),
        ("GET", "/v1/jobs/{j}/revisao", "curador", "vivo"),
        ("POST", "/v1/jobs/{j}/revisao/pulso", "curador", "vivo"),
    ],
)
def test_o_job_e_lido_uma_vez_por_pedido(
    metodo: str, rota: str, quem: str, job: str
) -> None:
    mundo = Mundo()
    mundo.jobs.leituras.clear()

    mundo.pedir(metodo, rota.format(j=job), _quem(mundo, quem))

    assert mundo.jobs.leituras == [job]


def test_cancelar_rele_e_cancela_se_o_job_andou_entre_a_leitura_e_a_troca() -> None:
    class AndaDepoisDaLeitura(RepositorioQueConta):
        def obter(self, job_id: str) -> Job | None:
            lido = super().obter(job_id)
            if len(self.leituras) == 1 and lido is not None:
                self.salvar(lido.model_copy(update={"estado": "validando"}))
            return lido

    mundo = Mundo(AndaDepoisDaLeitura())
    mundo.jobs.leituras.clear()

    resposta = mundo.cliente.delete("/v1/jobs/andando", headers=mundo.chave)

    assert resposta.status_code == 202
    assert resposta.json()["estado"] == "cancelado"
    assert mundo.jobs.leituras == ["andando", "andando"]
