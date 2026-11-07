"""O que a aba Revisão do painel da diretoria lê além das tabelas resumidas (#284): a taxa de
correção (#265), que vive no Firestore e no Storage, e o tempo de revisão (#251), agregado no
BigQuery (`api/revisao_do_painel.py`, #467).

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
from api.revisao_do_painel import (
    RevisaoAgregada,
    RevisaoNoVideo,
    TempoDeRevisao,
    agregar,
)
from api.taxa_de_correcao import LinhaDaTaxa, calcular

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


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
    ) -> RevisaoAgregada:
        """O tempo dos vídeos cujo último pulso é do período, já agrupado."""


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
        tempo: TempoDeRevisao,
    ) -> None:
        self._jobs = jobs
        self._tempo = tempo
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
    ) -> RevisaoAgregada:
        inicio, fim = _periodo(desde, ate)
        return self._tempo.tempo(inicio, fim, programa, usuario)


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
    ) -> RevisaoAgregada:
        return agregar(
            [
                t
                for t in self.tempos
                if (programa is None or t.programa == programa)
                and (usuario is None or t.uid == usuario)
            ]
        )
