"""Serviço de análise: manda o proxy ao Gemini e grava a decupagem.

O Workflows chama `POST /analisar` depois da validação. Só um Job em
`analisando` é processado; qualquer outro estado (evento repetido, Job já
concluído) responde 200 sem fazer nada. A falha da análise é tratada: o Job vai
a `falhou` e a resposta continua 200, para o Workflows não repetir a chamada.
"""

import os
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

import google.auth
from fastapi import FastAPI
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore
from google.cloud.storage import Bucket
from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel, ConfigDict

from api.decupagem import Video
from api.gemini import (
    AnaliseFalhou,
    SessaoHttp,
    Transporte,
    TransporteVertex,
    analisar,
)
from api.jobs import Job, RepositorioDeJobs, agora_utc
from api.nuvem import RepositorioFirestore, objeto_da_decupagem, objeto_do_proxy


class NovaAnalise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str


def _atualizar(
    repositorio: RepositorioDeJobs, job: Job, agora: datetime, **campos: object
) -> None:
    repositorio.salvar(job.model_copy(update={**campos, "atualizado_em": agora}))


def _cancelado(repositorio: RepositorioDeJobs, job_id: str) -> bool:
    """Relê o Job: o cancelamento pode ter chegado durante a chamada ao Gemini."""
    atual = repositorio.obter(job_id)
    return atual is not None and atual.estado == "cancelado"


def criar_app(
    repositorio: RepositorioDeJobs,
    decupagens: Bucket,
    transporte: Transporte,
    bucket_de_aceitos: str,
    dormir: Callable[[float], None] = time.sleep,
    relogio: Callable[[], datetime] = agora_utc,
) -> FastAPI:
    app = FastAPI(title="MAM RedeTV — análise")

    @app.post("/analisar")
    def analisar_job(corpo: NovaAnalise) -> dict[str, str]:
        job = repositorio.obter(corpo.job_id)
        if job is None or job.estado != "analisando":
            return {"status": "ignorado"}
        if job.sha256 is None or job.duracao_s is None:
            _atualizar(
                repositorio,
                job,
                relogio(),
                estado="falhou",
                codigo_falha="analise_falhou",
            )
            return {"status": "falhou"}
        try:
            decupagem = analisar(
                transporte,
                video_uri=f"gs://{bucket_de_aceitos}/{objeto_do_proxy(job.id)}",
                job_id=job.id,
                video=Video(sha256=job.sha256, duracao_ms=round(job.duracao_s * 1000)),
                dormir=dormir,
            )
        except AnaliseFalhou:
            if _cancelado(repositorio, job.id):
                return {"status": "cancelado"}
            _atualizar(
                repositorio,
                job,
                relogio(),
                estado="falhou",
                codigo_falha="analise_falhou",
            )
            return {"status": "falhou"}
        if _cancelado(repositorio, job.id):
            return {"status": "cancelado"}
        decupagens.blob(objeto_da_decupagem(job.id)).upload_from_string(
            decupagem.model_dump_json(), content_type="application/json"
        )
        _atualizar(repositorio, job, relogio(), estado="concluido")
        return {"status": "concluido"}

    return app


def _app_da_nuvem(projeto: str) -> FastAPI:
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = cast(SessaoHttp, AuthorizedSession(credenciais))  # type: ignore[no-untyped-call]
    return criar_app(
        RepositorioFirestore(firestore.Client(project=projeto)),
        ClienteStorage(project=projeto).bucket(os.environ["BUCKET_DECUPAGENS"]),
        TransporteVertex(projeto, sessao),
        os.environ["BUCKET_ACEITOS"],
    )


# No Cloud Run, o Terraform define o projeto; fora dele (testes) o app não existe.
_projeto = os.environ.get("GCP_PROJECT_ID")
app = _app_da_nuvem(_projeto) if _projeto else None
