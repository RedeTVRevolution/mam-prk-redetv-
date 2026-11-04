"""Quem abriu e quem baixou cada vídeo (E8): o registro na auditoria.

A abertura é gravada no pedido da reprodução, no servidor, e no máximo uma vez por
pessoa e vídeo a cada 30 minutos, para a renovação da URL do player não contar como
nova abertura. O download grava um registro por pedido, antes de a URL sair.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal

from api.auditoria import FiltroDeAuditoria, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import Chamador, Sistema
from api.jobs import AcaoDeDownload, Job, ServicoIndisponivel

JANELA_DA_ABERTURA = timedelta(minutes=30)

log = logging.getLogger(__name__)


def _quem(chamador: Chamador) -> dict[str, Any]:
    if isinstance(chamador, Sistema):
        return {"sistema": chamador.sistema}
    return {"uid": chamador.uid, "email": chamador.email}


def _e_dele(r: RegistroDeAuditoria, chamador: Chamador) -> bool:
    # Pelo uid, não pelo e-mail: o registro guarda o e-mail sem maiúsculas e o token não.
    if isinstance(chamador, Sistema):
        return r.sistema == chamador.sistema
    return r.uid == chamador.uid


class AcessosNaAuditoria:
    def __init__(
        self, auditoria: RepositorioDeAuditoria, relogio: Callable[[], datetime]
    ) -> None:
        self._auditoria = auditoria
        self._relogio = relogio

    def _gravar(
        self,
        chamador: Chamador,
        job: Job,
        acao: Literal["video.aberto"] | AcaoDeDownload,
        agora: datetime,
    ) -> None:
        self._auditoria.acrescentar(
            RegistroDeAuditoria(
                id=uuid.uuid4().hex,
                quando=agora,
                **_quem(chamador),
                acao=acao,
                alvo_tipo="job",
                alvo_id=job.id,
                alvo_nome=job.nome,
            )
        )

    def abriu(self, chamador: Chamador, job: Job) -> None:
        """Não derruba a reprodução: a falha fica no log."""
        agora = self._relogio()
        try:
            recentes = self._auditoria.consultar(
                FiltroDeAuditoria(
                    alvo_id=job.id, acao="video.aberto", de=agora - JANELA_DA_ABERTURA
                )
            ).registros
            if not any(_e_dele(r, chamador) for r in recentes):
                self._gravar(chamador, job, "video.aberto", agora)
        except Exception:
            log.exception("Falha ao registrar a abertura do vídeo %s", job.id)

    def baixou(
        self,
        chamador: Chamador,
        job: Job,
        acao: AcaoDeDownload,
    ) -> None:
        try:
            self._gravar(chamador, job, acao, self._relogio())
        except Exception:
            log.exception("Falha ao registrar %s do vídeo %s", acao, job.id)
            raise ServicoIndisponivel from None
