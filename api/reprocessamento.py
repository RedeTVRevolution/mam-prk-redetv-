"""Reprocessar um Job a partir da etapa que falhou (E8, Entradas).

A rota muda o Job pelo ciclo de vida, registra na auditoria e só então dispara o
Workflows na etapa de partida; se o disparo falha, devolve o Job ao que era.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StringConstraints

from api.auditoria import RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.ciclo_de_vida import (
    NaoReprocessavel,
    desfazer_reprocessamento,
    reprocessar,
)
from api.jobs import (
    JobPublico,
    NomeDaEtapa,
    RepositorioDeJobs,
    ServicoIndisponivel,
    _confere_permissao,
)


class DisparoDoWorkflow(Protocol):
    """Porta para o Workflows; os testes usam uma versão em memória."""

    def iniciar(self, job_id: str, etapa: NomeDaEtapa) -> None:
        """Começa uma execução que roda `etapa` e as seguintes; as anteriores não rodam."""
        ...


class DisparoEmMemoria:
    def __init__(self) -> None:
        self.disparos: list[tuple[str, NomeDaEtapa]] = []

    def iniciar(self, job_id: str, etapa: NomeDaEtapa) -> None:
        self.disparos.append((job_id, etapa))


class DisparoIndisponivel:
    def iniciar(self, job_id: str, etapa: NomeDaEtapa) -> None:
        raise ServicoIndisponivel


class PedidoDeReprocessamento(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None
    ) = None


def _exige_reprocessar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `video.reprocessar`; chave de sistema não reprocessa."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não reprocessa")
    _confere_permissao(request, chamador, "video.reprocessar")
    return chamador


def criar_rotas_do_reprocessamento(
    repositorio: RepositorioDeJobs,
    auditoria: RepositorioDeAuditoria,
    disparo: DisparoDoWorkflow,
    relogio: Callable[[], datetime],
) -> APIRouter:
    rotas = APIRouter(prefix="/jobs")

    @rotas.post("/{job_id}/reprocessar", status_code=202)
    def reprocessar_job(
        job_id: str,
        pessoa: Annotated[Usuario, Depends(_exige_reprocessar)],
        pedido: PedidoDeReprocessamento | None = None,
    ) -> JobPublico:
        agora = relogio()
        try:
            trocado = reprocessar(repositorio, job_id, agora)
        except NaoReprocessavel as erro:
            raise HTTPException(409, str(erro)) from None
        if trocado is None:
            raise HTTPException(404, "Job não encontrado")
        antes, job = trocado
        etapa = job.etapa_atual
        assert etapa is not None
        try:
            # O Job já mudou: o registro vem antes do disparo, para nunca haver
            # reprocessamento sem rastro.
            auditoria.acrescentar(
                RegistroDeAuditoria(
                    id=uuid.uuid4().hex,
                    quando=agora,
                    uid=pessoa.uid,
                    email=pessoa.email,
                    acao="video.reprocessado",
                    alvo_tipo="job",
                    alvo_id=job.id,
                    alvo_nome=job.nome,
                    motivo=pedido.motivo if pedido else None,
                    detalhes={"etapa": etapa},
                )
            )
            disparo.iniciar(job.id, etapa)
        except Exception:
            # Sem execução no Workflows o Job ficaria andando sem ninguém rodando.
            desfazer_reprocessamento(repositorio, antes, job, relogio())
            raise
        return JobPublico.de(job)

    return rotas
