"""Dono do ciclo de vida do Job: toda mudança de `estado` passa por aqui.

Cada transição diz de qual estado sai e para qual vai, e só acontece se o Job
ainda estiver na origem. A troca condicional é atômica no repositório; quem a
pediu recebe `None` quando ela não aconteceu (por exemplo, o Job foi cancelado
no meio do caminho).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

# `api.jobs` usa este módulo nas rotas; aqui os tipos só servem à checagem.
if TYPE_CHECKING:
    from api.jobs import CodigoDeFalha, Estado, Job, RepositorioDeJobs

TRANSICOES: dict[Estado, frozenset[Estado]] = {
    "aguardando_upload": frozenset({"validando", "falhou", "cancelado"}),
    "validando": frozenset({"analisando", "falhou", "cancelado"}),
    "analisando": frozenset({"concluido", "falhou", "cancelado"}),
    "concluido": frozenset(),
    "falhou": frozenset(),
    "cancelado": frozenset(),
}
FINAIS = frozenset(e for e, destinos in TRANSICOES.items() if not destinos)


class TransicaoProibida(Exception):
    def __init__(self, de: Estado, para: Estado) -> None:
        super().__init__(f"Transição fora da tabela: {de} → {para}")


class JaTerminou(Exception):
    """O Job está num estado final que não é `cancelado`."""

    def __init__(self, estado: Estado) -> None:
        super().__init__(estado)
        self.estado = estado


def transitar(
    repositorio: RepositorioDeJobs,
    job_id: str,
    de: Estado,
    para: Estado,
    agora: datetime,
    *,
    codigo_falha: CodigoDeFalha | None = None,
    sha256: str | None = None,
    duracao_s: float | None = None,
    cortes_ms: Sequence[int] | None = None,
    timecode_origem: str | None = None,
) -> Job | None:
    """O Job já em `para`, ou `None` se ele não estava mais em `de`."""
    if para not in TRANSICOES[de]:
        raise TransicaoProibida(de, para)
    mudancas: dict[str, Any] = {"estado": para, "atualizado_em": agora}
    if codigo_falha is not None:
        mudancas["codigo_falha"] = codigo_falha
    if sha256 is not None:
        mudancas["sha256"] = sha256
    if duracao_s is not None:
        mudancas["duracao_s"] = duracao_s
    if cortes_ms is not None:
        mudancas["cortes_ms"] = list(cortes_ms)
    if timecode_origem is not None:
        mudancas["timecode_origem"] = timecode_origem
    return repositorio.transitar(job_id, de, mudancas)


def cancelar(
    repositorio: RepositorioDeJobs, job_id: str, agora: datetime
) -> Job | None:
    """Cancela o Job; cancelar um já cancelado devolve o Job sem mudar nada."""
    while (job := repositorio.obter(job_id)) is not None:
        if job.estado == "cancelado":
            return job
        if job.estado in FINAIS:
            raise JaTerminou(job.estado)
        # Se o Job andou entre a leitura e a troca, lê de novo: os estados só avançam.
        if novo := transitar(repositorio, job_id, job.estado, "cancelado", agora):
            return novo
    return None
