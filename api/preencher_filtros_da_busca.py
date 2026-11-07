"""Carga dos objetos antigos da busca (#483): `make preencher-filtros-da-busca`.

Dá `sistema` e `na_lixeira` (os campos de filtro do índice, #482) aos objetos que ainda não
os têm, com o valor que o Job tem agora. Passa pelos Jobs concluídos (os da lixeira também)
em páginas e só escreve o que falta: repetir não muda nada, e uma carga interrompida
recomeça de onde parou, porque o objeto que já tem o campo não é escrito de novo. Cada
escrita passa pelo orçamento da cota da coleção (#460), e o 429 é tentado de novo. O
`batchUpdate` não recalcula o embedding automático: só o texto de `significado` o refaz.
"""

import logging
import os
import sys

from google.cloud import firestore

from api import log_estruturado
from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.indice_da_busca import IndiceDaBusca
from api.jobs import FiltroDeJobs, RepositorioDeJobs
from api.nuvem import RepositorioFirestore
from api.orcamento_de_escrita import OrcamentoFirestore

log = logging.getLogger(__name__)

POR_LOTE = 500


def preencher(
    repositorio: RepositorioDeJobs,
    indice: IndiceDaBusca,
    por_lote: int = POR_LOTE,
) -> dict[str, int]:
    """Devolve quantos `objetos` atualizou, em quantos `videos`, e quantos `falhou` (o
    índice recusou; o vídeo fica para a próxima rodada)."""
    contagem = {"videos": 0, "objetos": 0, "falhou": 0}
    cursor: str | None = None
    while True:
        pagina = repositorio.consultar(
            FiltroDeJobs(na_lixeira=None, limite=por_lote, cursor=cursor)
        )
        for job in pagina.jobs:
            if job.estado != "concluido":
                continue
            try:
                mudou = indice.preencher_filtros(
                    job.id, job.sistema, job.lixeira is not None
                )
            except Exception:
                log.exception("filtros da busca não preenchidos para %s", job.id)
                contagem["falhou"] += 1
                continue
            if mudou:
                contagem["videos"] += 1
                contagem["objetos"] += mudou
        cursor = pagina.proximo_cursor
        if cursor is None:
            return contagem


def main() -> int:
    firestore_ = firestore.Client(project=os.environ["GCP_PROJECT_ID"])
    contagem = preencher(
        RepositorioFirestore(firestore_),
        AgentRetrieval(
            ConfigDaBusca.do_ambiente(os.environ),
            transporte_http(),
            tentar_no_429=True,
            orcamento=OrcamentoFirestore(firestore_),
        ),
    )
    for nome, quantos in contagem.items():
        print(f"{nome}: {quantos}")
    return 1 if contagem["falhou"] else 0


if __name__ == "__main__":
    log_estruturado.configurar(logging.WARNING)
    sys.exit(main())
