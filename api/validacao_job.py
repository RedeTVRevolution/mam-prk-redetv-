"""Ponto de entrada do Cloud Run Job de validação.

O Workflows passa o id do Job em `JOB_ID`. O arquivo da quarentena chega
montado como volume só de leitura, e a saída vai para um volume em memória.
O Eventarc entrega pelo menos uma vez, então um evento repetido não faz nada.
"""

import logging
import os
from pathlib import Path

from google.cloud.storage import Bucket
from google.cloud.storage import Client as ClienteStorage

from api import log_estruturado
from api.bancos import cliente_do_firestore
from api.ciclo_de_vida import transitar
from api.cortes import LIMIAR_PADRAO
from api.eventos_do_job import jobs_do_ambiente
from api.jobs import RepositorioDeJobs
from api.jobs import agora_utc as agora
from api.nuvem import (
    objeto_da_copia_limpa,
    objeto_do_audio,
    objeto_do_proxy,
)
from api.validador import Recusa, validar

TIPO_DO_VIDEO = "video/mp4"
TIPO_DO_AUDIO = "audio/wav"


def executar(
    job_id: str,
    repositorio: RepositorioDeJobs,
    quarentena: Bucket,
    aceitos: Bucket,
    entrada: Path,
    saida: Path,
    limiar_de_cortes: float = LIMIAR_PADRAO,
) -> None:
    """`entrada` é a pasta da quarentena montada; o objeto tem o nome do id."""
    job = repositorio.obter(job_id)
    if job is None or job.estado != "aguardando_upload":
        return
    if not transitar(repositorio, job_id, "aguardando_upload", "validando", agora()):
        return
    try:
        aceito = validar(entrada / job_id, saida / job_id, limiar_de_cortes)
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
    # As mesmas chaves que a análise e os quadros-chave leem.
    for arquivo, objeto in (
        (aceito.copia_limpa, objeto_da_copia_limpa(job_id)),
        (aceito.proxy, objeto_do_proxy(job_id)),
    ):
        aceitos.blob(objeto).upload_from_filename(
            str(arquivo), content_type=TIPO_DO_VIDEO
        )
    if aceito.audio is not None:
        # A mesma chave que o Job de transcrição lê.
        aceitos.blob(objeto_do_audio(job_id)).upload_from_filename(
            str(aceito.audio), content_type=TIPO_DO_AUDIO
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
        cortes_ms=aceito.cortes_ms,
        timecode_origem=aceito.timecode_origem,
        taxa_de_quadros=aceito.taxa_de_quadros,
    )


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    storage = ClienteStorage(project=projeto)
    executar(
        os.environ["JOB_ID"],
        jobs_do_ambiente(cliente_do_firestore(projeto)),
        storage.bucket(os.environ["BUCKET_QUARENTENA"]),
        storage.bucket(os.environ["BUCKET_ACEITOS"]),
        Path(os.environ.get("QUARENTENA_MONTADA", "/quarentena")),
        Path(os.environ["TMPDIR"]),
        float(os.environ.get("LIMIAR_DE_CORTES", LIMIAR_PADRAO)),
    )


if __name__ == "__main__":
    # Sem isto o Python cai no manejador padrão, em texto puro (#475).
    log_estruturado.configurar(logging.WARNING)
    main()
