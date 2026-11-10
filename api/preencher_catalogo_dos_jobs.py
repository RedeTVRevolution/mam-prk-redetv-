"""Carga dos Jobs antigos (#359): `make preencher-catalogo-dos-jobs`.

Calcula `pessoas_do_catalogo` e `marcas_do_catalogo` de todos os Jobs concluídos (os da
lixeira também) a partir da Decupagem entregue. É uma passada única de linha de comando,
que lê os Jobs em páginas (`POR_LOTE`) e só grava o que mudou: repetir não muda nada.
Também reconcilia o Job que ficou sem o campo porque a gravação do #359 falhou
(`make recalcular-pessoas-dos-jobs`, #478).
"""

import logging
import os
import sys
from collections.abc import Callable

from google.cloud.storage import Client as ClienteStorage

from api.bancos import cliente_do_firestore
from api.catalogo import PessoaDoCatalogo
from api.catalogo_dos_jobs import (
    LeitorDeDecupagem,
    entregue_com_fundidas,
    gravar_se_mudou,
)
from api.correcoes import RepositorioDeCorrecoes
from api.jobs import FiltroDeJobs, RepositorioDeJobs
from api.nuvem import (
    CatalogoFirestore,
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
)

log = logging.getLogger(__name__)

POR_LOTE = 500


def preencher(
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    pessoas: Callable[[str], PessoaDoCatalogo | None],
    por_lote: int = POR_LOTE,
) -> dict[str, int]:
    """Devolve quantos Jobs `gravados`, `iguais` (ou que saíram de `concluido` no meio) e
    `falhou` (decupagem não lida)."""
    contagem = {"gravados": 0, "iguais": 0, "falhou": 0}
    cursor: str | None = None
    while True:
        pagina = repositorio.consultar(
            FiltroDeJobs(na_lixeira=None, limite=por_lote, cursor=cursor)
        )
        for job in pagina.jobs:
            if job.estado != "concluido":
                continue
            try:
                entregue = entregue_com_fundidas(job.id, decupagens, correcoes, pessoas)
            except Exception:
                log.exception("decupagem de %s não lida", job.id)
                contagem["falhou"] += 1
                continue
            if not gravar_se_mudou(repositorio, job.id, entregue):
                contagem["iguais"] += 1
                continue
            contagem["gravados"] += 1
        cursor = pagina.proximo_cursor
        if cursor is None:
            break
    return contagem


def main() -> int:
    projeto = os.environ["GCP_PROJECT_ID"]
    firestore_ = cliente_do_firestore(projeto)
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
