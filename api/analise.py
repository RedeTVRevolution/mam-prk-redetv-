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
from typing import Any, Protocol, cast

import google.auth
from fastapi import FastAPI
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel, ConfigDict

from api.ciclo_de_vida import transitar
from api.decupagem import Video
from api.gemini import (
    AnaliseFalhou,
    SessaoHttp,
    Transporte,
    TransporteVertex,
    analisar,
)
from api.jobs import RepositorioDeJobs, agora_utc
from api.nuvem import DecupagensStorage, RepositorioFirestore


class NovaAnalise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str


class DecupagensDaAnalise(Protocol):
    """Porta do Cloud Storage para a análise; os testes usam um dublê em memória."""

    def uri_do_proxy(self, job_id: str) -> str: ...

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None: ...


def criar_app(
    repositorio: RepositorioDeJobs,
    decupagens: DecupagensDaAnalise,
    transporte: Transporte,
    dormir: Callable[[float], None] = time.sleep,
    relogio: Callable[[], datetime] = agora_utc,
) -> FastAPI:
    app = FastAPI(title="MAM RedeTV — análise")

    @app.post("/analisar")
    def analisar_job(corpo: NovaAnalise) -> dict[str, str]:
        job = repositorio.obter(corpo.job_id)
        if job is None or job.estado != "analisando":
            return {"status": "ignorado"}

        def falhar() -> dict[str, str]:
            falhou = transitar(
                repositorio,
                job.id,
                "analisando",
                "falhou",
                relogio(),
                codigo_falha="analise_falhou",
            )
            return {"status": "falhou" if falhou else "cancelado"}

        if job.sha256 is None or job.duracao_s is None:
            return falhar()
        try:
            decupagem = analisar(
                transporte,
                video_uri=decupagens.uri_do_proxy(job.id),
                job_id=job.id,
                programa=job.programa,
                video=Video(sha256=job.sha256, duracao_ms=round(job.duracao_s * 1000)),
                dormir=dormir,
            )
        except AnaliseFalhou:
            return falhar()
        # A Decupagem só fica visível com o Job `concluido`: se o cancelamento
        # chegou antes da transição, o arquivo gravado aqui não é lido por ninguém.
        decupagens.gravar_decupagem(job.id, decupagem.model_dump_json())
        if transitar(repositorio, job.id, "analisando", "concluido", relogio()):
            return {"status": "concluido"}
        return {"status": "cancelado"}

    return app


def _app_da_nuvem(projeto: str) -> FastAPI:
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = cast(SessaoHttp, AuthorizedSession(credenciais))  # type: ignore[no-untyped-call]
    return criar_app(
        RepositorioFirestore(firestore.Client(project=projeto)),
        DecupagensStorage(
            ClienteStorage(project=projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        TransporteVertex(projeto, sessao),
    )


# No Cloud Run, o Terraform define o projeto; fora dele (testes) o app não existe.
_projeto = os.environ.get("GCP_PROJECT_ID")
app = _app_da_nuvem(_projeto) if _projeto else None
