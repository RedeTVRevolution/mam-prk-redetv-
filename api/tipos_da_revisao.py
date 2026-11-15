"""Os tipos do tempo de revisão que o painel lê, sem Firestore nem Storage (#653)."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class RevisaoNoVideo:
    """O tempo ativo de uma pessoa num vídeo (o acumulado dela nele, não só o do período: a
    medida guarda só o total), o programa do Job e a duração do vídeo (a do Job, como no
    `GET /v1/jobs/{id}/revisao`; sem ela, a que a medida trouxe)."""

    job_id: str
    uid: str
    email: str
    programa: str | None
    ativo_s: float
    duracao_s: float | None


@dataclass(frozen=True)
class NumerosAgregados:
    """Os vídeos de um grupo: o tempo ativo, o que cabe nos vídeos com duração, quantos
    vídeos e as horas deles (a duração conta uma vez por vídeo, mesmo revisado por duas
    pessoas)."""

    ativo_s: float
    ativo_com_duracao_s: float
    videos: int
    horas: float


@dataclass(frozen=True)
class RevisaoAgregada:
    total: NumerosAgregados
    por_pessoa: dict[tuple[str, str], NumerosAgregados]
    por_programa: dict[str | None, NumerosAgregados]
    por_pessoa_e_programa: dict[tuple[str, str, str], NumerosAgregados]


SEM_REVISAO = NumerosAgregados(0.0, 0.0, 0, 0.0)


class TempoDeRevisao(Protocol):
    def tempo(
        self,
        inicio: datetime | None,
        fim: datetime | None,
        programa: str | None,
        usuario: str | None,
    ) -> RevisaoAgregada:
        """As medidas cujo último pulso está em `[inicio, fim)`, agrupadas."""


def _numeros(medidas: list[RevisaoNoVideo]) -> NumerosAgregados:
    duracao: dict[str, float] = {}
    for m in medidas:
        if m.duracao_s:
            duracao[m.job_id] = max(duracao.get(m.job_id, 0), m.duracao_s)
    return NumerosAgregados(
        ativo_s=sum(m.ativo_s for m in medidas),
        ativo_com_duracao_s=sum(m.ativo_s for m in medidas if m.job_id in duracao),
        videos=len({m.job_id for m in medidas}),
        horas=sum(duracao.values()) / 3600,
    )


def agregar(medidas: list[RevisaoNoVideo]) -> RevisaoAgregada:
    """O agrupamento que o BigQuery faz, em memória (o dublê e a conferência da consulta)."""
    pessoas: dict[tuple[str, str], list[RevisaoNoVideo]] = defaultdict(list)
    programas: dict[str | None, list[RevisaoNoVideo]] = defaultdict(list)
    pessoas_e_programas: dict[tuple[str, str, str], list[RevisaoNoVideo]] = defaultdict(
        list
    )
    for m in medidas:
        pessoas[(m.uid, m.email)].append(m)
        programas[m.programa].append(m)
        pessoas_e_programas[(m.uid, m.email, m.programa or "")].append(m)
    return RevisaoAgregada(
        total=_numeros(medidas),
        por_pessoa={k: _numeros(v) for k, v in pessoas.items()},
        por_programa={k: _numeros(v) for k, v in programas.items()},
        por_pessoa_e_programa={k: _numeros(v) for k, v in pessoas_e_programas.items()},
    )
