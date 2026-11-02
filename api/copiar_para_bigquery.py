"""Carga das decupagens que já existem no BigQuery (#260): `make copiar-para-bigquery [JOB=...]`.

Só a cópia: o índice da busca não é tocado. Grava o estado da cópia no Job, como a
indexação; repetir dá o mesmo resultado.
"""

import logging
import os
import sys
from collections.abc import Callable
from datetime import datetime

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.copia_bigquery import (
    CopiaDosMomentos,
    copia_do_ambiente,
    linhas_da_decupagem,
)
from api.correcoes import RepositorioDeCorrecoes
from api.indexacao import LeitorDeDecupagem, _registrar, decupagem_do_job
from api.jobs import CopiaNoBigQuery, EstadoDaCopia, Job, RepositorioDeJobs, agora_utc
from api.nuvem import (
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
)

log = logging.getLogger(__name__)


def copiar(
    job: Job,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    copia: CopiaDosMomentos,
    relogio: Callable[[], datetime] = agora_utc,
) -> str:
    """Copia o vídeo e devolve o estado: `copiado`, `falhou` ou `ignorado` (não concluído)."""
    if job.estado != "concluido":
        return "ignorado"
    inicio = relogio()
    _registrar(
        repositorio,
        job.id,
        "copia_bigquery",
        CopiaNoBigQuery(estado="pendente", em=inicio),
    )
    estado: EstadoDaCopia = "copiado"
    try:
        decupagem = decupagem_do_job(job, decupagens, correcoes)
        copia.gravar(
            job.id,
            linhas_da_decupagem(
                job.id, decupagem, job.programa, job.data_exibicao, inicio
            ),
        )
    except Exception:
        log.exception("cópia para o BigQuery falhou para %s", job.id)
        estado = "falhou"
    _registrar(
        repositorio,
        job.id,
        "copia_bigquery",
        CopiaNoBigQuery(estado=estado, em=relogio(), desde=inicio),
    )
    return estado


def copiar_jobs(
    ids: list[str] | None,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    copia: CopiaDosMomentos,
) -> dict[str, str]:
    """Copia os Jobs de `ids`, ou todos os concluídos; devolve o estado de cada um."""
    resultado: dict[str, str] = {}
    jobs: list[Job] = []
    if ids:
        for i in ids:
            if (job := repositorio.obter(i)) is None:
                resultado[i] = "inexistente"
            else:
                jobs.append(job)
    else:
        jobs = [
            j
            for j in repositorio.listar()
            if j.estado == "concluido" and j.lixeira is None
        ]
    for job in jobs:
        resultado[job.id] = copiar(job, repositorio, decupagens, correcoes, copia)
    return resultado


def main(argv: list[str]) -> int:
    copia = copia_do_ambiente(os.environ)
    if copia is None:
        print("BIGQUERY_DATASET não definido", file=sys.stderr)
        return 2
    projeto = os.environ["GCP_PROJECT_ID"]
    firestore_ = firestore.Client(project=projeto)
    resultado = copiar_jobs(
        argv or None,
        RepositorioFirestore(firestore_),
        DecupagensStorage(
            ClienteStorage(project=projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        RepositorioDeCorrecoesFirestore(firestore_),
        copia,
    )
    for job_id, estado in resultado.items():
        print(f"{job_id}: {estado}")
    return 1 if {"falhou", "inexistente"} & set(resultado.values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
