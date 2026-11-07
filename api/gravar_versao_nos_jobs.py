"""Carga dos Jobs antigos (#494): `make gravar-versao-nos-jobs`.

Grava `versao_pipeline` no Job concluído que ainda não a tem, lendo-a da decupagem (os da
lixeira também). Passada única de linha de comando, em lotes: baixa cada decupagem uma
vez, só dos Jobs sem o campo, então repetir não muda nada. Job cuja decupagem não tem a
versão (anterior ao campo) ou não foi lida fica como está, e `make reprocessar-versao` o
trata como de versão desconhecida.

Ambiente: `GCP_PROJECT_ID`, `BUCKET_ACEITOS`, `BUCKET_DECUPAGENS`.
"""

import os
import sys
from itertools import batched
from typing import Any

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.jobs import Job
from api.nuvem import COLECAO_DE_JOBS, DecupagensStorage
from api.reprocessar_versao import ANTERIOR, LeitorDeDecupagem, versao_da_decupagem

LOTE = 400  # o limite do Firestore é 500 gravações por lote


def gravar(colecao: Any, cliente: Any, decupagens: LeitorDeDecupagem) -> dict[str, int]:
    """Devolve quantos Jobs `gravados`, `iguais` (já tinham a versão), `sem_versao` (a
    decupagem não a tem) e `nao_lidos` (a decupagem não foi lida)."""
    contagem = {"gravados": 0, "iguais": 0, "sem_versao": 0, "nao_lidos": 0}
    a_gravar: list[tuple[Any, str]] = []
    for doc in colecao.stream():
        job = Job(**(doc.to_dict() or {}))
        if job.estado != "concluido":
            continue
        if job.versao_pipeline is not None:
            contagem["iguais"] += 1
            continue
        versao = versao_da_decupagem(decupagens, job.id)
        if versao is None:
            contagem["nao_lidos"] += 1
        elif versao == ANTERIOR:
            contagem["sem_versao"] += 1
        else:
            a_gravar.append((doc.reference, versao))
    for lote in batched(a_gravar, LOTE):
        escrita = cliente.batch()
        for referencia, versao in lote:
            escrita.update(referencia, {"versao_pipeline": versao})
        escrita.commit()
        contagem["gravados"] += len(lote)
    return contagem


def main() -> int:
    projeto = os.environ["GCP_PROJECT_ID"]
    cliente = firestore.Client(project=projeto)
    decupagens = DecupagensStorage(
        ClienteStorage(project=projeto),
        os.environ["BUCKET_ACEITOS"],
        os.environ["BUCKET_DECUPAGENS"],
    )
    contagem = gravar(cliente.collection(COLECAO_DE_JOBS), cliente, decupagens)
    for nome, quantos in contagem.items():
        print(f"{nome}: {quantos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
