"""Adaptadores de nuvem da E0: Firestore (Jobs) e Cloud Storage (upload)."""

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import google.auth
import google.auth.transport.requests
from google.api_core.exceptions import NotFound
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.jobs import (
    PRAZO_DO_UPLOAD,
    ArmazenamentoIndisponivel,
    Job,
    ServicoIndisponivel,
)

COLECAO_DE_JOBS = "jobs"
TAMANHO_DO_PEDACO = 256 * 1024


def objeto_do_proxy(job_id: str) -> str:
    return f"{job_id}/proxy.mp4"


def objeto_da_decupagem(job_id: str) -> str:
    return f"{job_id}.json"


class RepositorioFirestore:
    def __init__(
        self, cliente: firestore.Client, colecao: str = COLECAO_DE_JOBS
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def salvar(self, job: Job) -> None:
        self._colecao.document(job.id).set(job.model_dump())

    def obter(self, job_id: str) -> Job | None:
        doc = self._colecao.document(job_id).get()
        return Job(**(doc.to_dict() or {})) if doc.exists else None

    def listar(self) -> list[Job]:
        docs = self._colecao.order_by(
            "criado_em", direction=firestore.Query.DESCENDING
        ).stream()
        return [Job(**(doc.to_dict() or {})) for doc in docs]


def assinatura_pelo_iam() -> dict[str, Any]:
    """Assinatura pedida ao IAM pela conta do serviço, sem chave em arquivo."""
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credenciais.refresh(google.auth.transport.requests.Request())
    return {
        "service_account_email": credenciais.service_account_email,
        "access_token": credenciais.token,
    }


class ArmazenamentoStorage(ArmazenamentoIndisponivel):
    """Upload, reprodução e decupagem; o cancelamento do upload segue indisponível."""

    def __init__(
        self,
        cliente: ClienteStorage,
        bucket_de_quarentena: str,
        bucket_de_aceitos: str,
        bucket_de_decupagens: str,
        assinatura: Callable[[], dict[str, Any]] = assinatura_pelo_iam,
    ) -> None:
        self._cliente = cliente
        self._bucket = bucket_de_quarentena
        self._aceitos = bucket_de_aceitos
        self._decupagens = bucket_de_decupagens
        self._assinatura = assinatura

    def url_de_upload(self, job_id: str, tamanho_bytes: int, tipo: str) -> str:
        blob = self._cliente.bucket(self._bucket).blob(job_id)
        url: str = blob.generate_signed_url(
            version="v4",
            expiration=PRAZO_DO_UPLOAD,
            method="POST",
            content_type=tipo,
            headers={
                "x-goog-resumable": "start",
                "x-upload-content-length": str(tamanho_bytes),
            },
            **self._assinatura(),
        )
        return url

    def url_de_reproducao(self, job_id: str, validade: timedelta) -> str:
        blob = self._cliente.bucket(self._aceitos).blob(objeto_do_proxy(job_id))
        url: str = blob.generate_signed_url(
            version="v4", expiration=validade, method="GET", **self._assinatura()
        )
        return url

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        blob = self._cliente.bucket(self._decupagens).blob(objeto_da_decupagem(job_id))
        try:
            with blob.open("rb") as arquivo:
                while pedaco := arquivo.read(TAMANHO_DO_PEDACO):
                    yield pedaco
        except NotFound as e:
            raise ServicoIndisponivel from e
