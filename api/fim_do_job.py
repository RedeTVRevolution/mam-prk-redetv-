"""Avisa o fim do Job que o Workflows deu como `falhou` (#379).

O Workflows grava `falhou` direto no Firestore quando a execução de um Job estoura o
tempo, fica sem memória ou morre. Esse caminho não passa pelo repositório da API, então
ele chama este Cloud Run Job logo depois de gravar: ele publica o evento de fim de Job (o
que vira webhook, `api.eventos_do_job`) e o evento de uso `fim_de_processamento`, com a
mesma forma dos que a API publica. Um Job por execução, com `JOB_ID`.

A falha é reclamada antes de publicar: o Job guarda em qual `reprocessamentos` ela já foi
avisada, então a mesma falha marcada duas vezes publica uma vez, e a falha de um
reprocessamento novo publica de novo. Se a publicação falhar, o erro vai ao log e a
falha segue marcada como avisada, como no caminho da API (o evento não é refeito). A hora
dos eventos é a da falha (`atualizado_em`, que o Workflows grava com o `falhou`), não a de
quando este Job roda.

Ambiente: `GCP_PROJECT_ID`, `JOB_ID`, `PUBSUB_TOPICO_EVENTOS` e `PUBSUB_TOPICO_USO`.
"""

import logging
import os
import sys
from collections.abc import Mapping
from typing import Any

from google.cloud import firestore

from api import log_estruturado
from api.comparar_objetos import FaltaNoAmbiente, exigir_do_ambiente
from api.eventos_de_uso import Eventos
from api.eventos_do_job import (
    PublicadorDeEventos,
    PublicadorPubSub,
    eventos_do_ambiente,
    publicar_fim,
    registrar_o_fim,
    transporte_do_pubsub,
)
from api.jobs import Job, RepositorioDeJobs
from api.webhook import RepositorioDeWebhooks


def avisar_o_fim(
    job_id: str,
    repositorio: RepositorioDeJobs,
    webhooks: RepositorioDeWebhooks,
    publicador: PublicadorDeEventos,
    eventos: Eventos,
) -> bool:
    """`True` se publicou. Não publica se o Job não existe, não está `falhou` ou se essa
    falha já foi avisada."""

    def reclamar(job: Job) -> dict[str, Any] | None:
        if (
            job.estado != "falhou"
            or job.fim_avisado_no_reprocessamento == job.reprocessamentos
        ):
            return None
        return {"fim_avisado_no_reprocessamento": job.reprocessamentos}

    job = repositorio.trocar(job_id, reclamar)
    if job is None:
        return False
    publicar_fim(job, webhooks, publicador, job.atualizado_em)
    registrar_o_fim(eventos, job, job.atualizado_em)
    return True


def main(ambiente: Mapping[str, str] = os.environ) -> int:
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        job_id = exigir_do_ambiente(ambiente, "JOB_ID")
        topico = exigir_do_ambiente(ambiente, "PUBSUB_TOPICO_EVENTOS")
        # Sem o tópico de uso, `eventos_do_ambiente` descartaria o evento em silêncio.
        exigir_do_ambiente(ambiente, "PUBSUB_TOPICO_USO")
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    from api.nuvem import RepositorioDeWebhooksFirestore, RepositorioFirestore

    cliente = firestore.Client(project=projeto)
    avisar_o_fim(
        job_id,
        RepositorioFirestore(cliente),
        RepositorioDeWebhooksFirestore(cliente),
        PublicadorPubSub(topico, transporte_do_pubsub()),
        eventos_do_ambiente(ambiente),
    )
    return 0


if __name__ == "__main__":
    # Sem isto o Python cai no manejador padrão, em texto puro (#475).
    log_estruturado.configurar(logging.WARNING)
    sys.exit(main())
