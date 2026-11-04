"""Painel da diretoria (E9): quem pode ver e o registro de cada acesso na auditoria.

A abertura do painel e cada exportação em CSV gravam quem, quando e o filtro.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException, Request

from api.auditoria import RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.jobs import ServicoIndisponivel, _confere_permissao

log = logging.getLogger(__name__)


def exige_painel(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência das rotas do painel: só pessoa com `painel.ver`; chave de sistema não vê."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não vê o painel")
    _confere_permissao(request, chamador, "painel.ver")
    return chamador


class AcessosAoPainel:
    def __init__(
        self, auditoria: RepositorioDeAuditoria, relogio: Callable[[], datetime]
    ) -> None:
        self._auditoria = auditoria
        self._relogio = relogio

    def _gravar(
        self,
        pessoa: Usuario,
        acao: Literal["painel.aberto", "painel.exportado"],
        filtro: dict[str, Any],
    ) -> None:
        try:
            self._auditoria.acrescentar(
                RegistroDeAuditoria(
                    id=uuid.uuid4().hex,
                    quando=self._relogio(),
                    uid=pessoa.uid,
                    email=pessoa.email,
                    acao=acao,
                    alvo_tipo="painel",
                    alvo_id="diretoria",
                    alvo_nome="Painel da diretoria",
                    detalhes={"filtro": filtro},
                )
            )
        except Exception:
            # Sem registro, nada sai: o acesso sem rastro não passa.
            log.exception("Falha ao registrar %s de %s", acao, pessoa.uid)
            raise ServicoIndisponivel from None

    def abriu(self, pessoa: Usuario, filtro: dict[str, Any]) -> None:
        self._gravar(pessoa, "painel.aberto", filtro)

    def exportou(self, pessoa: Usuario, filtro: dict[str, Any]) -> None:
        self._gravar(pessoa, "painel.exportado", filtro)
