"""Ponto de entrada do Cloud Run Job de validação.

O Workflows passa o id do Job em `JOB_ID`. O arquivo da quarentena chega
montado como volume só de leitura, e a saída vai para um volume em memória.
O Eventarc entrega pelo menos uma vez, então um evento repetido não faz nada.
"""

import os
from pathlib import Path

from google.cloud import firestore
from google.cloud.storage import Bucket
from google.cloud.storage import Client as ClienteStorage

from api.ciclo_de_vida import transitar
from api.jobs import RepositorioDeJobs
from api.jobs import agora_utc as agora
from api.nuvem import RepositorioFirestore
from api.validador import Recusa, validar

TIPO_DO_VIDEO = "video/mp4"


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
    if not transitar(repositorio, job_id, "aguardando_upload", "validando", agora()):
        return
    try:
        aceito = validar(entrada / job_id, saida / job_id)
    except Recusa as recusa:
        if transitar(
            repositorio,
            job_id,
            "validando",
            "falhou",
            agora(),
            codigo_falha=recusa.codigo,
        ):
            quarentena.blob(job_id).delete()
        return
    # Releitura só para não subir arquivos à toa; quem decide é a transição.
    atual = repositorio.obter(job_id)
    if atual is None or atual.estado != "validando":
        return
    for arquivo in (aceito.copia_limpa, aceito.proxy):
        aceitos.blob(f"{job_id}/{arquivo.name}").upload_from_filename(
            str(arquivo), content_type=TIPO_DO_VIDEO
        )
    quarentena.blob(job_id).delete()
    transitar(
        repositorio,
        job_id,
        "validando",
        "analisando",
        agora(),
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
