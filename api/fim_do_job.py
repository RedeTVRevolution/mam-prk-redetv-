"""Avisa o fim do Job que o Workflows deu como `falhou` (#379).

O Workflows grava `falhou` direto no Firestore quando a execução de um Job estoura o
tempo, fica sem memória ou morre. Esse caminho não passa pelo repositório da API, então
ele chama este Cloud Run Job logo depois de gravar: ele publica o evento de fim de Job (o
que vira webhook, `api.eventos_do_job`) e o evento de uso `fim_de_processamento`, com a
mesma forma dos que a API publica. Um Job por execução, com `JOB_ID`.

Cada evento é marcado no Job (em qual `reprocessamentos`) logo depois de sair, e a falha
só fica avisada depois dos dois: a mesma falha marcada duas vezes publica uma vez, e a
falha de um reprocessamento novo publica de novo. Se a publicação falhar, o Job sai com
erro, o Cloud Run o repete e a repetição envia só o que não saiu (#691). O evento do
webhook leva o mesmo id nas duas tentativas. A hora dos eventos é a da falha (`atualizado_em`, que o Workflows grava com o `falhou`), não a de
quando este Job roda.

Ambiente: `GCP_PROJECT_ID`, `JOB_ID`, `PUBSUB_TOPICO_EVENTOS` e `PUBSUB_TOPICO_USO`.
"""

import logging
import os
import sys
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from api import log_estruturado
from api.ambiente import FaltaNoAmbiente, exigir_do_ambiente
from api.bancos import cliente_do_firestore
from api.eventos_de_uso import Eventos
from api.eventos_do_job import (
    PublicadorDeEventos,
    PublicadorPubSub,
    enviar_o_fim,
    eventos_do_ambiente,
    registrar_o_fim,
    transporte_do_pubsub,
)
from api.modelo_do_job import FiltroDeJobs, Job, RepositorioDeJobs
from api.webhook import RepositorioDeWebhooks

log = logging.getLogger(__name__)


def _id_estavel(job: Job, evento: str, sufixo: str | None = None) -> str:
    """O mesmo em toda tentativa de avisar a mesma falha: o duplicado que a repetição pode
    gerar (marca que falhou depois de publicar) é descartado por quem recebe."""
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"mam/{evento}/{job.id}/{job.reprocessamentos if sufixo is None else sufixo}",
    ).hex


def avisar_o_fim(
    job_id: str,
    repositorio: RepositorioDeJobs,
    webhooks: RepositorioDeWebhooks,
    publicador: PublicadorDeEventos,
    eventos: Eventos,
) -> bool:
    """`True` se avisou. Não avisa se o Job não existe, não está `falhou` ou se essa
    falha já foi avisada. A falha de publicação sobe: o Job de aviso sai com erro e o
    Cloud Run o repete, e a repetição pula o evento já marcado."""
    job = repositorio.obter(job_id)
    if (
        job is None
        or job.estado != "falhou"
        or job.fim_avisado_no_reprocessamento == job.reprocessamentos
    ):
        return False
    n = job.reprocessamentos

    def marcar(campo: str) -> bool:
        """`False` se o Job já foi reprocessado: este aviso é de uma passada antiga e
        não pode sobrescrever os marcadores do aviso novo."""
        return (
            repositorio.trocar(
                job_id,
                lambda atual: {campo: n} if atual.reprocessamentos == n else None,
            )
            is not None
        )

    if job.fim_webhook_enviado_no_reprocessamento != n:
        # Sem webhook cadastrado não há o que enviar, e isso não é erro.
        enviar_o_fim(
            job, webhooks, publicador, job.atualizado_em, _id_estavel(job, "webhook")
        )
        if not marcar("fim_webhook_enviado_no_reprocessamento"):
            return False
    if job.fim_uso_enviado_no_reprocessamento != n:
        registrar_o_fim(
            eventos, job, job.atualizado_em, _id_estavel(job, "uso"), levantar=True
        )
        if not marcar("fim_uso_enviado_no_reprocessamento"):
            return False
    return marcar("fim_avisado_no_reprocessamento")


def _tirar(repositorio: RepositorioDeJobs, job_id: str, parte: str) -> None:
    """A marca durável de que a parte saiu."""
    repositorio.trocar(
        job_id,
        lambda atual: {"fim_a_avisar": [p for p in atual.fim_a_avisar if p != parte]},
    )


def avisar_fins_pendentes(
    repositorio: RepositorioDeJobs,
    webhooks: RepositorioDeWebhooks,
    publicador: PublicadorDeEventos,
    eventos: Eventos,
    agora: datetime,
) -> int:
    """O fim dos uploads que a varredura expirou (#782): publica o que falta de cada Job com
    `fim_a_avisar` e tira a parte de lá logo depois de o evento sair; devolve quantos Jobs
    ficaram sem pendência. Cada evento leva a hora `agora` (a tabela dos Jobs e os resumos
    só leem os últimos dias pela hora do evento). O do webhook mantém o id entre tentativas;
    o do painel ganha um novo a cada uma, porque a repetição de um evento já publicado cairia
    fora da janela de deduplicação e a falha seria contada de novo. A falha de uma parte não
    segura a outra nem os outros Jobs: vai ao log e a próxima varredura repete só o que falta."""
    resolvidos = 0
    for job in repositorio.consultar(
        FiltroDeJobs(com_fim_a_avisar=True, na_lixeira=None)
    ).jobs:
        sem_falha = True
        try:
            if "webhook" in job.fim_a_avisar:
                # `False` (sem webhook cadastrado) também encerra a parte.
                enviar_o_fim(
                    job,
                    webhooks,
                    publicador,
                    agora,
                    _id_estavel(job, "webhook", "upload_expirado"),
                )
                _tirar(repositorio, job.id, "webhook")
        except Exception:
            sem_falha = False
            log.exception("não consegui avisar o fim do upload expirado de %s", job.id)
        try:
            if "uso" in job.fim_a_avisar:
                registrar_o_fim(eventos, job, agora, levantar=True)
                _tirar(repositorio, job.id, "uso")
        except Exception:
            sem_falha = False
            log.exception("não consegui avisar o fim do upload expirado de %s", job.id)
        resolvidos += sem_falha
    return resolvidos


def dependencias_do_aviso(
    cliente: Any, ambiente: Mapping[str, str]
) -> tuple[RepositorioDeJobs, RepositorioDeWebhooks, PublicadorDeEventos, Eventos]:
    from api.nuvem import RepositorioDeWebhooksFirestore, RepositorioFirestore

    return (
        RepositorioFirestore(cliente),
        RepositorioDeWebhooksFirestore(cliente),
        PublicadorPubSub(
            exigir_do_ambiente(ambiente, "PUBSUB_TOPICO_EVENTOS"),
            transporte_do_pubsub(),
        ),
        eventos_do_ambiente(ambiente),
    )


def exigir_os_topicos_do_aviso(ambiente: Mapping[str, str]) -> None:
    exigir_do_ambiente(ambiente, "PUBSUB_TOPICO_EVENTOS")
    # Sem o tópico de uso, `eventos_do_ambiente` descartaria o evento em silêncio.
    exigir_do_ambiente(ambiente, "PUBSUB_TOPICO_USO")


def main(ambiente: Mapping[str, str] = os.environ) -> int:
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        job_id = exigir_do_ambiente(ambiente, "JOB_ID")
        exigir_os_topicos_do_aviso(ambiente)
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    cliente = cliente_do_firestore(projeto, ambiente)
    try:
        avisar_o_fim(job_id, *dependencias_do_aviso(cliente, ambiente))
    except Exception:
        # Saída com erro: o Cloud Run repete o Job (`max_retries`) e a repetição envia
        # só o que ainda não saiu.
        log.exception("não consegui avisar o fim do Job %s", job_id)
        return 1
    return 0


if __name__ == "__main__":
    # Sem isto o Python cai no manejador padrão, em texto puro (#475).
    log_estruturado.configurar(logging.WARNING)
    sys.exit(main())
