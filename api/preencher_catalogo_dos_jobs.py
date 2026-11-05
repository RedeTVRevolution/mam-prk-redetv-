"""Carga dos Jobs antigos (#359): `make preencher-catalogo-dos-jobs`.

Calcula `pessoas_do_catalogo` e `marcas_do_catalogo` de todos os Jobs concluídos (os da
lixeira também) a partir da Decupagem entregue. É uma passada única de linha de comando,
então lê o acervo inteiro. Só grava o Job que mudou: repetir não muda nada.
"""

import logging
import os
import sys
from collections.abc import Callable

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.catalogo import PessoaDoCatalogo
from api.catalogo_dos_jobs import entregue_com_fundidas, ids_do_catalogo
from api.correcoes import RepositorioDeCorrecoes
from api.jobs import FiltroDeJobs, RepositorioDeJobs
from api.nuvem import (
    CatalogoFirestore,
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
)

log = logging.getLogger(__name__)


def preencher(
    repositorio: RepositorioDeJobs,
    decupagens: object,
    correcoes: RepositorioDeCorrecoes,
    pessoas: Callable[[str], PessoaDoCatalogo | None],
) -> dict[str, int]:
    """Devolve quantos Jobs `gravados`, `iguais` e `falhou` (decupagem não lida)."""
    contagem = {"gravados": 0, "iguais": 0, "falhou": 0}
    for job in repositorio.consultar(FiltroDeJobs(na_lixeira=None)).jobs:
        if job.estado != "concluido":
            continue
        try:
            entregue = entregue_com_fundidas(job.id, decupagens, correcoes, pessoas)
        except Exception:
            log.exception("decupagem de %s não lida", job.id)
            contagem["falhou"] += 1
            continue
        de_pessoas, de_marcas = ids_do_catalogo(entregue)
        if (
            job.pessoas_do_catalogo == de_pessoas
            and job.marcas_do_catalogo == de_marcas
        ):
            contagem["iguais"] += 1
            continue
        repositorio.transitar(
            job.id,
            "concluido",
            {"pessoas_do_catalogo": de_pessoas, "marcas_do_catalogo": de_marcas},
        )
        contagem["gravados"] += 1
    return contagem


def main() -> int:
    projeto = os.environ["GCP_PROJECT_ID"]
    firestore_ = firestore.Client(project=projeto)
    contagem = preencher(
        RepositorioFirestore(firestore_),
        DecupagensStorage(
            ClienteStorage(project=projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        RepositorioDeCorrecoesFirestore(firestore_),
        CatalogoFirestore(firestore_).obter,
    )
    for nome, quantos in contagem.items():
        print(f"{nome}: {quantos}")
    return 1 if contagem["falhou"] else 0


if __name__ == "__main__":
    sys.exit(main())
