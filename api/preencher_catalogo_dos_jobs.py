"""Carga dos Jobs antigos (#359): `make preencher-catalogo-dos-jobs`.

Calcula `pessoas_do_catalogo` e `marcas_do_catalogo` de todos os Jobs concluídos (os da
lixeira também) a partir da Decupagem corrigida (a leitura que mantém o vínculo de quem está na lixeira
do catálogo). É uma passada única de linha de comando,
que lê os Jobs em páginas e só grava o que mudou: repetir não muda nada.
Também reconcilia o Job que ficou sem o campo porque a gravação do #359 falhou
(`make recalcular-pessoas-dos-jobs`, #478).
"""

import logging
import os
import sys

from api.ambiente import FaltaNoAmbiente
from api.bancos import cliente_do_firestore
from api.catalogo_dos_jobs import gravar_se_mudou
from api.ferramentas.comum import TAMANHO_DA_PAGINA, jobs_concluidos
from api.leitura_da_decupagem import LeituraDaDecupagem
from api.modelo_do_job import RepositorioDeJobs
from api.nuvem import (
    CatalogoFirestore,
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
)

log = logging.getLogger(__name__)


def preencher(
    repositorio: RepositorioDeJobs,
    leitura: LeituraDaDecupagem,
    tamanho_da_pagina: int = TAMANHO_DA_PAGINA,
) -> dict[str, int]:
    """Devolve quantos Jobs `gravados`, `iguais` (ou que saíram de `concluido` no meio) e
    `falhou` (decupagem não lida)."""
    contagem = {"gravados": 0, "iguais": 0, "falhou": 0}
    for job in jobs_concluidos(
        repositorio, na_lixeira=None, tamanho_da_pagina=tamanho_da_pagina
    ):
        try:
            corrigida = leitura.corrigida(job.id)
        except Exception:
            log.exception("decupagem de %s não lida", job.id)
            contagem["falhou"] += 1
            continue
        if not gravar_se_mudou(repositorio, job.id, corrigida):
            contagem["iguais"] += 1
            continue
        contagem["gravados"] += 1
    return contagem


def main() -> int:
    try:
        decupagens = DecupagensStorage.do_ambiente()
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    firestore_ = cliente_do_firestore(os.environ["GCP_PROJECT_ID"])
    contagem = preencher(
        RepositorioFirestore(firestore_),
        LeituraDaDecupagem(
            decupagens,
            RepositorioDeCorrecoesFirestore(firestore_),
            CatalogoFirestore(firestore_),
        ),
    )
    for nome, quantos in contagem.items():
        print(f"{nome}: {quantos}")
    return 1 if contagem["falhou"] else 0


if __name__ == "__main__":
    sys.exit(main())
