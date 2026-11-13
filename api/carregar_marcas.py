"""`make carregar-marcas`: carga inicial do catálogo de marcas (#150).

Acrescenta ao Firestore as marcas dos comerciais das Decupagens dos Jobs concluídos
que ainda não estão lá; rodar de novo não duplica nenhuma. Usa as credenciais da
máquina; sem teste automático contra a nuvem (a carga em si é testada com o dublê).
"""

import logging
import os
import sys
from collections.abc import Iterable, Iterator
from typing import Any

from google.cloud.storage import Client as ClienteStorage

from api.bancos import cliente_do_firestore
from api.leitura_da_decupagem import LeituraDaDecupagem
from api.marcas import carregar_marcas
from api.nuvem import (
    CatalogoDeMarcasFirestore,
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
)

log = logging.getLogger(__name__)


def decupagens_dos_jobs(
    jobs: Iterable[Any], decupagens: Any, correcoes: Any
) -> Iterator[dict[str, Any]]:
    """A Decupagem corrigida (com as correções que valem) de cada Job concluído; um
    Job cuja Decupagem não abre ou não lê é pulado com log, e a carga segue."""
    leitura = LeituraDaDecupagem(decupagens, correcoes)
    for job in jobs:
        if job.estado != "concluido":
            continue
        try:
            yield leitura.corrigida(job.id)
        except Exception:  # noqa: BLE001 - uma Decupagem ruim não para a carga
            log.warning("decupagem de %s não lida; marcas dela ficam de fora", job.id)


if __name__ == "__main__":
    projeto = os.environ.get("GCP_PROJECT_ID") or sys.exit("defina GCP_PROJECT_ID")
    cliente = cliente_do_firestore(projeto)
    entraram = carregar_marcas(
        CatalogoDeMarcasFirestore(cliente),
        decupagens_dos_jobs(
            RepositorioFirestore(cliente).listar(),
            DecupagensStorage(
                ClienteStorage(project=projeto),
                os.environ["BUCKET_ACEITOS"],
                os.environ["BUCKET_DECUPAGENS"],
            ),
            RepositorioDeCorrecoesFirestore(cliente),
        ),
    )
    print(f"{entraram} marca(s) acrescentada(s) ao catálogo")
