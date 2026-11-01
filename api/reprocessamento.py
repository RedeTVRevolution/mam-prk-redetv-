"""Reprocessar um Job (E8): a partir da etapa que falhou (Entradas) ou de uma etapa
escolhida num Job concluído (Visualizador).

A rota muda o Job pelo ciclo de vida, registra na auditoria e só então dispara o
Workflows na etapa de partida; se o disparo falha, devolve o Job ao que era. Com a
análise escolhida, o progresso das janelas é apagado antes do disparo, para o Gemini
rodar de novo em todas elas.
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
from api.progresso_das_janelas import JanelasDoJob


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
    # Só num Job concluído; a lista das etapas permitidas é do ciclo de vida (409).
    etapa: str | None = None


def _exige_pessoa(chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: chave de sistema não reprocessa."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não reprocessa")
    return chamador


def criar_rotas_do_reprocessamento(
    repositorio: RepositorioDeJobs,
    auditoria: RepositorioDeAuditoria,
    disparo: DisparoDoWorkflow,
    relogio: Callable[[], datetime],
    janelas: JanelasDoJob | None = None,
) -> APIRouter:
    rotas = APIRouter(prefix="/jobs")

    @rotas.post("/{job_id}/reprocessar", status_code=202)
    def reprocessar_job(
        job_id: str,
        request: Request,
        pessoa: Annotated[Usuario, Depends(_exige_pessoa)],
        pedido: PedidoDeReprocessamento | None = None,
    ) -> JobPublico:
        escolhida = pedido.etapa if pedido else None
        # `video.reprocessar` refaz o que falhou; refazer um vídeo bom é do Curador.
        _confere_permissao(
            request,
            pessoa,
            "video.reprocessar" if escolhida is None else "video.reprocessar_etapa",
        )
        if escolhida is not None and not (pedido and pedido.motivo):
            raise HTTPException(422, "Informe o motivo do reprocessamento")
        agora = relogio()
        try:
            trocado = reprocessar(repositorio, job_id, agora, escolhida)
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
                    detalhes={"etapa": etapa}
                    | ({"etapa_escolhida": True} if escolhida else {}),
                )
            )
            if escolhida == "analise" and janelas is not None:
                janelas.apagar(job.id)
            disparo.iniciar(job.id, etapa)
        except Exception:
            # Sem execução no Workflows o Job ficaria andando sem ninguém rodando.
            desfazer_reprocessamento(repositorio, antes, job, relogio())
            raise
        return JobPublico.de(job)

    return rotas
