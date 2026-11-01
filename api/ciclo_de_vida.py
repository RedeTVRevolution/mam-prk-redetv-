"""Dono do ciclo de vida do Job: toda mudança de `estado` passa por aqui.

Cada transição diz de qual estado sai e para qual vai, e só acontece se o Job
ainda estiver na origem. A troca condicional é atômica no repositório; quem a
pediu recebe `None` quando ela não aconteceu (por exemplo, o Job foi cancelado
no meio do caminho).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

# `api.jobs` usa este módulo nas rotas; aqui os tipos só servem à checagem.
if TYPE_CHECKING:
    from api.jobs import (
        CodigoDeFalha,
        Estado,
        Job,
        NomeDaEtapa,
        RepositorioDeJobs,
        ResultadoDaEtapa,
    )

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
    taxa_de_quadros: float | None = None,
) -> Job | None:
    """O Job já em `para`, ou `None` se ele não estava mais em `de`."""
    if para not in TRANSICOES[de]:
        raise TransicaoProibida(de, para)
    mudancas: dict[str, Any] = {"estado": para, "atualizado_em": agora}
    if para == "concluido":
        # Quem indexa (api.indexacao) troca este estado ao terminar.
        from api.jobs import Indexacao

        mudancas["indexacao"] = Indexacao(estado="pendente", em=agora)
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
    if taxa_de_quadros is not None:
        mudancas["taxa_de_quadros"] = taxa_de_quadros
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


def _gravar_etapa(
    repositorio: RepositorioDeJobs,
    job_id: str,
    mudar: Callable[[Job], dict[str, Any]],
    exige: Callable[[Job], bool] = lambda job: True,
) -> Job | None:
    """Grava a mudança de etapa sem mudar o `estado` do Job (nem exigir um).

    É a mesma troca condicional das transições, com o estado lido na hora: se o Job
    andou entre a leitura e a troca, lê de novo. `None` se o Job não existe ou não
    atende a `exige`.
    """
    while (job := repositorio.obter(job_id)) is not None and exige(job):
        if novo := repositorio.transitar(job_id, job.estado, mudar(job)):
            return novo
    return None


def iniciar_etapa(
    repositorio: RepositorioDeJobs,
    job_id: str,
    etapa: NomeDaEtapa,
    agora: datetime,
) -> Job | None:
    """Abre a etapa (refazê-la, como no reprocessar, recomeça o relógio dela)."""
    from api.jobs import Etapa

    return _gravar_etapa(
        repositorio,
        job_id,
        lambda job: {
            "etapa_atual": etapa,
            "etapas": {**job.etapas, etapa: Etapa(inicio=agora)},
            "atualizado_em": agora,
        },
    )


def encerrar_etapa(
    repositorio: RepositorioDeJobs,
    job_id: str,
    etapa: NomeDaEtapa,
    resultado: ResultadoDaEtapa,
    agora: datetime,
) -> Job | None:
    """Fecha a etapa com o resultado. `None` se o Job não existe ou a etapa não começou.

    A falha de uma etapa não muda o `estado` do Job: quem o derruba é a transição
    `analisando` → `falhou`; uma etapa depois do `concluido` só fica `falhou`.
    """

    def mudar(job: Job) -> dict[str, Any]:
        aberta = job.etapas[etapa]
        return {
            "etapa_atual": None if job.etapa_atual == etapa else job.etapa_atual,
            "etapas": {
                **job.etapas,
                etapa: aberta.model_copy(update={"fim": agora, "resultado": resultado}),
            },
            "atualizado_em": agora,
        }

    return _gravar_etapa(
        repositorio, job_id, mudar, exige=lambda job: etapa in job.etapas
    )
