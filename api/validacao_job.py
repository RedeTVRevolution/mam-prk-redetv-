"""Ponto de entrada do Cloud Run Job de validação.

O Workflows passa o id do Job em `JOB_ID`. O arquivo da quarentena chega
montado como volume só de leitura, e a saída vai para um volume em memória.
O Eventarc entrega pelo menos uma vez, então um evento repetido não faz nada.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

from google.cloud import firestore
from google.cloud.storage import Bucket
from google.cloud.storage import Client as ClienteStorage

from api.jobs import Job, RepositorioDeJobs
from api.nuvem import RepositorioFirestore
from api.validador import Recusa, validar

TIPO_DO_VIDEO = "video/mp4"


def _atualizar(repositorio: RepositorioDeJobs, job: Job, **campos: object) -> Job:
    atualizado = job.model_copy(update={**campos, "atualizado_em": datetime.now(UTC)})
    repositorio.salvar(atualizado)
    return atualizado


def executar(
    job_id: str,
    repositorio: RepositorioDeJobs,
    quarentena: Bucket,
    aceitos: Bucket,
    entrada: Path,
    saida: Path,
) -> None:
    """`entrada` é a pasta da quarentena montada; o objeto tem o nome do id."""
    job = repositorio.obter(job_id)
    if job is None or job.estado != "aguardando_upload":
        return
    job = _atualizar(repositorio, job, estado="validando")
    try:
        aceito = validar(entrada / job_id, saida / job_id)
    except Recusa as recusa:
        _atualizar(repositorio, job, estado="falhou", codigo_falha=recusa.codigo)
        quarentena.blob(job_id).delete()
        return
    for arquivo in (aceito.copia_limpa, aceito.proxy):
        aceitos.blob(f"{job_id}/{arquivo.name}").upload_from_filename(
            str(arquivo), content_type=TIPO_DO_VIDEO
        )
    quarentena.blob(job_id).delete()
    _atualizar(
        repositorio,
        job,
        estado="analisando",
        sha256=aceito.sha256,
        duracao_s=aceito.duracao_s,
    )


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    storage = ClienteStorage(project=projeto)
    executar(
        os.environ["JOB_ID"],
        RepositorioFirestore(firestore.Client(project=projeto)),
        storage.bucket(os.environ["BUCKET_QUARENTENA"]),
        storage.bucket(os.environ["BUCKET_ACEITOS"]),
        Path(os.environ.get("QUARENTENA_MONTADA", "/quarentena")),
        Path(os.environ["TMPDIR"]),
    )


if __name__ == "__main__":
    main()
