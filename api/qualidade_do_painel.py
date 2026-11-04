"""O que a aba Revisão do painel da diretoria lê além das tabelas resumidas (#284): a taxa de
correção (#265) e o tempo de revisão (#251), que vivem no Firestore e no Storage.

O período chega em dias de São Paulo, os dois inclusive, e vira `[desde, ate)` em UTC. A
taxa de correção lê a decupagem de cada Job com correção ou pulso no período: é a consulta
mais cara do painel e só a aba Revisão a faz.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from api.correcoes import RepositorioDeCorrecoes
from api.jobs import RepositorioDeJobs
from api.reprocessar_versao import LeitorDeDecupagem
from api.revisao import RepositorioDeRevisao
from api.taxa_de_correcao import LinhaDaTaxa, calcular

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


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


class QualidadeDoPainel(Protocol):
    def taxa_de_correcao(
        self, desde: date | None, ate: date | None, programa: str | None
    ) -> list[LinhaDaTaxa]:
        """Por programa, versão do pipeline e tipo de correção."""

    def tempo_de_revisao(
        self,
        desde: date | None,
        ate: date | None,
        programa: str | None,
        usuario: str | None,
    ) -> list[RevisaoNoVideo]:
        """Uma linha por pessoa e vídeo cujo último pulso é do período."""


def _periodo(
    desde: date | None, ate: date | None
) -> tuple[datetime | None, datetime | None]:
    return (
        datetime.combine(desde, time.min, SAO_PAULO).astimezone(UTC) if desde else None,
        datetime.combine(ate + timedelta(days=1), time.min, SAO_PAULO).astimezone(UTC)
        if ate
        else None,
    )


class QualidadeReal:
    def __init__(
        self,
        jobs: RepositorioDeJobs,
        decupagens: LeitorDeDecupagem,
        correcoes: RepositorioDeCorrecoes,
        revisao: RepositorioDeRevisao,
    ) -> None:
        self._jobs = jobs
        self._decupagens = decupagens
        self._correcoes = correcoes
        self._revisao = revisao

    def taxa_de_correcao(
        self, desde: date | None, ate: date | None, programa: str | None
    ) -> list[LinhaDaTaxa]:
        inicio, fim = _periodo(desde, ate)
        return calcular(
            self._jobs,
            self._decupagens,
            self._correcoes,
            self._revisao,
            inicio,
            fim,
            programa,
        )

    def tempo_de_revisao(
        self,
        desde: date | None,
        ate: date | None,
        programa: str | None,
        usuario: str | None,
    ) -> list[RevisaoNoVideo]:
        inicio, fim = _periodo(desde, ate)
        jobs = {j.id: j for j in self._jobs.listar()}
        return [
            RevisaoNoVideo(
                m.job_id,
                m.uid,
                m.email,
                jobs[m.job_id].programa,
                m.ativo_s,
                jobs[m.job_id].duracao_s or m.duracao_s,
            )
            for m in self._revisao.todas(inicio)
            if m.job_id in jobs
            and (fim is None or m.ultimo_pulso < fim)
            and (programa is None or jobs[m.job_id].programa == programa)
            and (usuario is None or m.uid == usuario)
        ]


@dataclass
class QualidadeEmMemoria:
    """Dublê: as linhas dadas, sem filtro."""

    taxa: list[LinhaDaTaxa]
    tempos: list[RevisaoNoVideo]

    def taxa_de_correcao(
        self, desde: date | None, ate: date | None, programa: str | None
    ) -> list[LinhaDaTaxa]:
        return [t for t in self.taxa if programa is None or t.programa == programa]

    def tempo_de_revisao(
        self,
        desde: date | None,
        ate: date | None,
        programa: str | None,
        usuario: str | None,
    ) -> list[RevisaoNoVideo]:
        return [
            t
            for t in self.tempos
            if (programa is None or t.programa == programa)
            and (usuario is None or t.uid == usuario)
        ]
