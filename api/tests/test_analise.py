"""Serviço de análise, contra os emuladores do Firestore e do Storage.

Sem `FIRESTORE_EMULATOR_HOST` / `STORAGE_EMULATOR_HOST`, os testes são pulados;
no CI os emuladores sobem antes do pytest. O Gemini é sempre o `TransporteFalso`.
"""

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.storage import Bucket
from google.cloud.storage import Client as ClienteStorage

from api.analise import criar_app
from api.auth import Usuario
from api.decupagem import Decupagem
from api.gemini import ErroHttp
from api.jobs import Job
from api.main import criar_app as criar_app_web
from api.nuvem import ArmazenamentoStorage, RepositorioFirestore
from api.tests.test_gemini import BOA, TransporteFalso
from api.tests.test_nuvem import _credencial_local

EMULADOR_FIRESTORE = os.environ.get("FIRESTORE_EMULATOR_HOST")
EMULADOR_STORAGE = os.environ.get("STORAGE_EMULATOR_HOST")
BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
DEPOIS = BASE + timedelta(minutes=5)
SHA = "a" * 64

pytestmark = pytest.mark.skipif(
    not (EMULADOR_FIRESTORE and EMULADOR_STORAGE), reason="sem emuladores"
)


@dataclass
class Ambiente:
    repositorio: RepositorioFirestore
    decupagens: Bucket
    transporte: TransporteFalso
    cliente: TestClient

    def registrar(self, job_id: str, estado: str = "analisando") -> Job:
        job = Job(
            id=job_id,
            nome=f"{job_id}.mp4",
            tamanho_bytes=10,
            sha256=SHA,
            duracao_s=60.0,
            estado=estado,  # type: ignore[arg-type]
            criado_por="uid-1",
            criado_em=BASE,
            atualizado_em=BASE,
        )
        self.repositorio.salvar(job)
        return job

    def job(self, job_id: str) -> Job:
        job = self.repositorio.obter(job_id)
        assert job is not None
        return job


def _ambiente(*respostas: str | Exception) -> Ambiente:
    sufixo = uuid.uuid4().hex[:8]
    storage = ClienteStorage(
        project="teste",
        credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
        client_options={"api_endpoint": EMULADOR_STORAGE},
    )
    repositorio = RepositorioFirestore(
        firestore.Client(
            project="teste",
            credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
        ),
        colecao=f"jobs-{sufixo}",
    )
    decupagens = storage.create_bucket(f"teste-decupagens-{sufixo}")
    transporte = TransporteFalso(*respostas)
    app = criar_app(
        repositorio,
        decupagens,
        transporte,
        bucket_de_aceitos=f"teste-aceitos-{sufixo}",
        dormir=lambda _s: None,
        relogio=lambda: DEPOIS,
    )
    return Ambiente(repositorio, decupagens, transporte, TestClient(app))


def _analisar(ambiente: Ambiente, job_id: str) -> int:
    return ambiente.cliente.post("/analisar", json={"job_id": job_id}).status_code


def test_sucesso_grava_a_decupagem_e_leva_o_job_a_concluido() -> None:
    ambiente = _ambiente(BOA)
    ambiente.registrar("j1")

    assert _analisar(ambiente, "j1") == 200

    job = ambiente.job("j1")
    assert (job.estado, job.codigo_falha) == ("concluido", None)
    assert job.atualizado_em == DEPOIS
    gravada = Decupagem.model_validate_json(
        ambiente.decupagens.blob("j1.json").download_as_bytes()
    )
    # O bloco `video` vem do Job, não do modelo.
    assert (gravada.video.sha256, gravada.video.duracao_ms) == (SHA, 60_000)
    chamada = ambiente.transporte.chamadas[0]
    assert chamada.video_uri.startswith("gs://teste-aceitos-")
    assert chamada.video_uri.endswith("/j1/proxy.mp4")
    assert chamada.rotulos == {"job_id": "j1"}


def test_analise_falhou_grava_falhou_sem_decupagem() -> None:
    ambiente = _ambiente(ErroHttp(400))
    ambiente.registrar("j2")

    assert _analisar(ambiente, "j2") == 200

    job = ambiente.job("j2")
    assert (job.estado, job.codigo_falha) == ("falhou", "analise_falhou")
    assert not ambiente.decupagens.blob("j2.json").exists()


@pytest.mark.parametrize(
    "estado", ["aguardando_upload", "validando", "concluido", "falhou"]
)
def test_job_fora_de_analisando_nao_muda(estado: str) -> None:
    ambiente = _ambiente()
    antes = ambiente.registrar("j3", estado)

    assert _analisar(ambiente, "j3") == 200

    assert ambiente.job("j3") == antes
    assert ambiente.transporte.chamadas == []
    assert not ambiente.decupagens.blob("j3.json").exists()


def test_job_inexistente_responde_200_sem_fazer_nada() -> None:
    ambiente = _ambiente()

    assert _analisar(ambiente, "fantasma") == 200

    assert ambiente.repositorio.obter("fantasma") is None
    assert ambiente.transporte.chamadas == []


def test_corpo_fora_do_esquema_estrito_e_recusado() -> None:
    ambiente = _ambiente()

    assert ambiente.cliente.post("/analisar", json={}).status_code == 422
    corpo = {"job_id": "j", "extra": 1}
    assert ambiente.cliente.post("/analisar", json=corpo).status_code == 422


def test_decupagem_gravada_e_servida_pela_api_web() -> None:
    ambiente = _ambiente(BOA)
    ambiente.registrar("j4")
    _analisar(ambiente, "j4")
    credencial = _credencial_local()
    armazenamento = ArmazenamentoStorage(
        ambiente.decupagens.client,
        "quarentena",
        "aceitos",
        ambiente.decupagens.name,
        assinatura=lambda: {"credentials": credencial},
    )

    class Verificador:
        def verificar(self, token: str) -> Usuario:
            return Usuario(uid="u", email="a@b.c")

    web = TestClient(criar_app_web(Verificador(), ambiente.repositorio, armazenamento))

    resposta = web.get("/v1/jobs/j4/decupagem", headers={"Authorization": "Bearer x"})

    assert resposta.status_code == 200
    assert resposta.json()["programa"]["resumo"] == "Jornal da noite"
    assert json.loads(resposta.content)["video"]["sha256"] == SHA
