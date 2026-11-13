"""Sinal por programa (#287): eventos por hora de vídeo contra o histórico do programa.

Depois que a cópia no BigQuery (#260) grava um vídeo, contamos os eventos dele (aparições,
menções, pautas e comerciais) por hora de vídeo e comparamos com a média e o desvio dos
últimos N vídeos do mesmo programa, calculados no BigQuery. Fora de K desvios, uma linha
JSON `desvio_de_programa` vai ao log e um alerta do Monitoring a pega (`infra/main.tf`).
Programa com menos de N vídeos no histórico não alerta; histórico sem variação (desvio
zero) também não, porque qualquer diferença daria um desvio infinito.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from api.copia_bigquery import (
    ConfigDoBigQuery,
    CopiaEmMemoria,
    LinhaDoMomento,
    Transporte,
    parametro,
    transporte_http,
)
from api.sinais import Registrar, imprimir

# Evento do sinal -> tipos de linha da cópia que o formam. É a ordem das colunas da consulta.
EVENTOS: dict[str, tuple[str, ...]] = {
    "aparicoes": ("aparicao",),
    "mencoes": ("mencao_na_fala", "mencao_no_texto"),
    "pautas": ("pauta",),
    "comerciais": ("comercial",),
}
HORA_MS = 3_600_000


@dataclass(frozen=True)
class Referencia:
    """A média e o desvio dos eventos por hora nos últimos vídeos do programa."""

    videos: int
    media: float
    desvio: float


@dataclass(frozen=True)
class Desvio:
    """Um evento do vídeo fora de K desvios da referência do programa."""

    tipo: str
    valor: float
    referencia: Referencia


@dataclass(frozen=True)
class ConfigDoSinal:
    videos: int  # N: quantos vídeos formam o histórico, e o mínimo para alertar
    desvios: float  # K

    @classmethod
    def do_ambiente(cls, ambiente: Mapping[str, str]) -> "ConfigDoSinal | None":
        if "SINAL_VIDEOS" not in ambiente:
            return None
        return cls(int(ambiente["SINAL_VIDEOS"]), float(ambiente["SINAL_DESVIOS"]))


class Historico(Protocol):
    def do_programa(
        self, programa: str, job_id: str, videos: int
    ) -> dict[str, Referencia]:
        """Os `videos` mais recentes do programa, fora `job_id`, por evento."""


def eventos_por_hora(linhas: list[LinhaDoMomento]) -> dict[str, float] | None:
    """Os eventos do vídeo por hora, ou `None` sem a duração (cópia antiga)."""
    duracao = next(
        (x.duracao_do_video_ms for x in linhas if x.duracao_do_video_ms), None
    )
    if not duracao:
        return None
    return {
        evento: round(sum(x.tipo in tipos for x in linhas) * HORA_MS / duracao, 4)
        for evento, tipos in EVENTOS.items()
    }


def _exibido_em(linhas: list[LinhaDoMomento]) -> date:
    return max(
        (x.data_de_exibicao for x in linhas if x.data_de_exibicao), default=date.min
    )


class HistoricoEmMemoria:
    """Dublê do histórico: as mesmas contas sobre a cópia em memória."""

    def __init__(self, copia: CopiaEmMemoria) -> None:
        self.copia = copia

    def do_programa(
        self, programa: str, job_id: str, videos: int
    ) -> dict[str, Referencia]:
        do_programa = [
            (linhas, taxas)
            for j, linhas in self.copia.por_job.items()
            if j != job_id
            and linhas
            and linhas[0].programa == programa
            and (taxas := eventos_por_hora(linhas)) is not None
        ]
        do_programa.sort(key=lambda x: _exibido_em(x[0]), reverse=True)
        recentes = [taxas for _, taxas in do_programa[:videos]]
        resposta: dict[str, Referencia] = {}
        for evento in EVENTOS:
            valores = [t[evento] for t in recentes]
            media = sum(valores) / len(valores) if valores else 0.0
            desvio = (
                (sum((v - media) ** 2 for v in valores) / (len(valores) - 1)) ** 0.5
                if len(valores) > 1
                else 0.0
            )
            resposta[evento] = Referencia(len(valores), media, desvio)
        return resposta


class HistoricoBigQuery:
    """O histórico real: a média e o desvio saem de uma consulta só."""

    def __init__(self, config: ConfigDoBigQuery, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def do_programa(
        self, programa: str, job_id: str, videos: int
    ) -> dict[str, Referencia]:
        c = self._config
        contagens = ",\n    ".join(
            f"COUNTIF(tipo IN ({', '.join(repr(t) for t in tipos)})) "
            f"* {HORA_MS} / ANY_VALUE(duracao_do_video_ms) AS {evento}"
            for evento, tipos in EVENTOS.items()
        )
        estatisticas = ",\n  ".join(
            f"AVG({e}) AS media_{e}, STDDEV_SAMP({e}) AS desvio_{e}" for e in EVENTOS
        )
        consulta = f"""
WITH por_video AS (
  SELECT
    job_id,
    MAX(data_de_exibicao) AS exibido,
    MAX(gravado_em) AS gravado,
    {contagens}
  FROM `{c.projeto}.{c.dataset}.{c.tabela}`
  WHERE programa = @programa AND job_id != @job_id AND duracao_do_video_ms > 0
  GROUP BY job_id
), recentes AS (
  SELECT * FROM por_video ORDER BY exibido DESC, gravado DESC LIMIT @n
)
SELECT COUNT(*) AS videos,
  {estatisticas}
FROM recentes
"""
        resposta = self._transporte(
            {
                "query": consulta,
                "useLegacySql": False,
                "location": c.regiao,
                "timeoutMs": 60_000,
                "queryParameters": [
                    parametro("programa", programa),
                    parametro("job_id", job_id),
                    parametro("n", str(videos), "INT64"),
                ],
            }
        )
        if not resposta.get("jobComplete", False):
            raise RuntimeError("a consulta do sinal por programa não terminou no prazo")
        celulas = [campo["v"] for campo in resposta["rows"][0]["f"]]
        total = int(celulas[0])
        return {
            evento: Referencia(
                total,
                float(celulas[1 + 2 * i] or 0),
                float(celulas[2 + 2 * i] or 0),
            )
            for i, evento in enumerate(EVENTOS)
        }


class SinalDoPrograma:
    def __init__(
        self, historico: Historico, config: ConfigDoSinal, registrar: Registrar
    ) -> None:
        self._historico = historico
        self._config = config
        self._registrar = registrar

    def avaliar(
        self, job_id: str, programa: str | None, linhas: list[LinhaDoMomento]
    ) -> list[Desvio]:
        """Loga um `desvio_de_programa` por evento fora de K desvios; devolve os desvios."""
        taxas = eventos_por_hora(linhas)
        if not programa or taxas is None:
            return []
        referencias = self._historico.do_programa(programa, job_id, self._config.videos)
        achados = [
            Desvio(evento, valor, ref)
            for evento, valor in taxas.items()
            if (ref := referencias[evento]).videos >= self._config.videos
            and ref.desvio > 0
            and abs(valor - ref.media) > self._config.desvios * ref.desvio
        ]
        for d in achados:
            self._registrar(
                registro_do_desvio(job_id, programa, d, self._config.desvios)
            )
        return achados


def registro_do_desvio(
    job_id: str, programa: str, desvio: Desvio, limite_de_desvios: float
) -> str:
    return json.dumps(
        {
            "severity": "WARNING",
            "evento": "desvio_de_programa",
            "job_id": job_id,
            "programa": programa,
            "tipo": desvio.tipo,
            "valor": desvio.valor,
            "media": round(desvio.referencia.media, 4),
            "desvio": round(desvio.referencia.desvio, 4),
            "videos_no_historico": desvio.referencia.videos,
            "limite_de_desvios": limite_de_desvios,
        },
        ensure_ascii=False,
    )


def sinal_do_ambiente(ambiente: Mapping[str, str]) -> "SinalDoPrograma | None":
    """O sinal configurado, ou `None` se o ambiente não traz N e K ou a cópia."""
    sinal = ConfigDoSinal.do_ambiente(ambiente)
    if sinal is None or "BIGQUERY_DATASET" not in ambiente:
        return None
    config = ConfigDoBigQuery.do_ambiente(ambiente)
    return SinalDoPrograma(
        HistoricoBigQuery(config, transporte_http(config.projeto)), sinal, imprimir
    )
