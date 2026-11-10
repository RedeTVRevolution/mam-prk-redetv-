"""Carga dos Jobs antigos (#479): `make gravar-mes-nos-jobs`.

Grava `mes_exibicao` (`AAAA-MM`) em todo Job que tem `data_exibicao` e ainda não tem o
campo certo (os da lixeira também). Passada única de linha de comando: lê o acervo inteiro,
grava em lotes e só toca o Job que mudou, então repetir não muda nada. Só depois dela se
liga `LISTAGEM_POR_MES` no Terraform.
"""

import os
import sys
from itertools import batched
from typing import Any

from api.bancos import cliente_do_firestore
from api.jobs import Job
from api.nuvem import COLECAO_DE_JOBS

LOTE = 400  # o limite do Firestore é 500 gravações por lote


def gravar(colecao: Any, cliente: Any) -> dict[str, int]:
    """Devolve quantos Jobs `gravados`, `iguais` e `sem_data`."""
    contagem = {"gravados": 0, "iguais": 0, "sem_data": 0}
    a_gravar: list[Any] = []
    for doc in colecao.stream():
        dados = doc.to_dict() or {}
        job = Job(**dados)
        if job.data_exibicao is None:
            contagem["sem_data"] += 1
        elif dados.get("mes_exibicao") == job.mes_exibicao:
            contagem["iguais"] += 1
        else:
            a_gravar.append((doc.reference, job.mes_exibicao))
    for lote in batched(a_gravar, LOTE):
        escrita = cliente.batch()
        for referencia, mes in lote:
            escrita.update(referencia, {"mes_exibicao": mes})
        escrita.commit()
        contagem["gravados"] += len(lote)
    return contagem


def main() -> int:
    cliente = cliente_do_firestore(os.environ["GCP_PROJECT_ID"])
    contagem = gravar(cliente.collection(COLECAO_DE_JOBS), cliente)
    for nome, quantos in contagem.items():
        print(f"{nome}: {quantos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
