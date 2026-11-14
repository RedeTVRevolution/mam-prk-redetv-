"""Tabela dos Jobs para a Revisão e o Custo do painel (#454): carga dos Jobs que já existem.

A consulta agendada `infra/modulos/mam/jobs_do_painel.sql` mantém a tabela a partir dos
eventos de uso; este módulo cobre o que veio antes deles: `make preencher-jobs-do-painel`
grava uma linha por Job do Firestore, num MERGE por lote (repetir dá o mesmo resultado).
"""

import json
import logging
import os
import sys
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol

from api.bancos import cliente_do_firestore
from api.copia_bigquery import Transporte, parametro, transporte_http
from api.jobs import Job, RepositorioDeJobs
from api.nuvem import RepositorioFirestore

log = logging.getLogger(__name__)

JOBS_POR_MERGE = 500


@dataclass(frozen=True)
class LinhaDoJob:
    id: str
    programa: str | None
    duracao_ms: int | None
    quem_tipo: str
    quem_id: str
    estado: str
    criado_em: datetime
    concluido_em: datetime | None
    atualizado_em: datetime


ESTADOS_DE_FIM = ("concluido", "falhou", "cancelado")


def linha_do_job(job: Job) -> LinhaDoJob:
    """Os campos que a Revisão e o Custo usam. O dono é o sistema, ou quem criou o Job
    (o mesmo `quem` do evento de uso); `concluido_em` só existe depois do fim. O estado
    segue o vocabulário da consulta agendada: antes do fim, `em_andamento`."""
    sistema = job.sistema is not None
    fim = job.estado in ESTADOS_DE_FIM
    return LinhaDoJob(
        id=job.id,
        programa=job.programa,
        duracao_ms=round(job.duracao_s * 1000) if job.duracao_s is not None else None,
        quem_tipo="sistema" if sistema else "usuario",
        quem_id=job.sistema if job.sistema is not None else job.criado_por,
        estado=job.estado if fim else "em_andamento",
        criado_em=job.criado_em,
        concluido_em=job.atualizado_em if fim else None,
        atualizado_em=job.atualizado_em,
    )


class TabelaDeJobs(Protocol):
    def gravar(self, linhas: list[LinhaDoJob]) -> None:
        """Insere as linhas; as que já havia dos mesmos Jobs são trocadas."""


class TabelaEmMemoria:
    """Dublê da tabela: uma linha por Job."""

    def __init__(self) -> None:
        self.por_id: dict[str, LinhaDoJob] = {}

    def gravar(self, linhas: list[LinhaDoJob]) -> None:
        for linha in linhas:
            self.por_id[linha.id] = linha


@dataclass(frozen=True)
class ConfigDaTabelaDeJobs:
    projeto: str
    dataset: str
    tabela: str
    regiao: str

    @classmethod
    def do_ambiente(cls, ambiente: Any) -> "ConfigDaTabelaDeJobs":
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            dataset=ambiente["BIGQUERY_DATASET"],
            tabela=ambiente["BIGQUERY_TABELA_DE_JOBS"],
            regiao=ambiente["BIGQUERY_REGIAO"],
        )


def _json_da_linha(linha: LinhaDoJob) -> dict[str, Any]:
    dados = asdict(linha)
    for campo in ("criado_em", "concluido_em", "atualizado_em"):
        valor = getattr(linha, campo)
        dados[campo] = valor.isoformat() if valor else None
    return dados


class TabelaBigQuery:
    """A tabela real: um MERGE por lote troca as linhas dos Jobs dele pelo `id`."""

    def __init__(self, config: ConfigDaTabelaDeJobs, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def gravar(self, linhas: list[LinhaDoJob]) -> None:
        c = self._config
        tabela = f"`{c.projeto}.{c.dataset}.{c.tabela}`"
        consulta = f"""
MERGE {tabela} AS t
USING (
  SELECT
    JSON_VALUE(l, '$.id') AS id,
    JSON_VALUE(l, '$.programa') AS programa,
    CAST(JSON_VALUE(l, '$.duracao_ms') AS INT64) AS duracao_ms,
    JSON_VALUE(l, '$.quem_tipo') AS quem_tipo,
    JSON_VALUE(l, '$.quem_id') AS quem_id,
    JSON_VALUE(l, '$.estado') AS estado,
    TIMESTAMP(JSON_VALUE(l, '$.criado_em')) AS criado_em,
    TIMESTAMP(JSON_VALUE(l, '$.concluido_em')) AS concluido_em,
    TIMESTAMP(JSON_VALUE(l, '$.atualizado_em')) AS atualizado_em
  FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@linhas))) AS l
) AS s
ON t.id = s.id
WHEN MATCHED THEN UPDATE SET
  programa = s.programa, duracao_ms = s.duracao_ms, quem_tipo = s.quem_tipo,
  quem_id = s.quem_id, estado = s.estado, criado_em = s.criado_em,
  concluido_em = s.concluido_em, atualizado_em = s.atualizado_em
WHEN NOT MATCHED THEN INSERT
  (id, programa, duracao_ms, quem_tipo, quem_id, estado, criado_em, concluido_em,
   atualizado_em)
VALUES
  (s.id, s.programa, s.duracao_ms, s.quem_tipo, s.quem_id, s.estado, s.criado_em,
   s.concluido_em, s.atualizado_em)
"""
        resposta = self._transporte(
            {
                "query": consulta,
                "useLegacySql": False,
                "location": c.regiao,
                "timeoutMs": 120_000,
                "queryParameters": [
                    parametro(
                        "linhas",
                        json.dumps(
                            [_json_da_linha(x) for x in linhas], ensure_ascii=False
                        ),
                    )
                ],
            }
        )
        if not resposta.get("jobComplete", False):
            raise RuntimeError(f"carga de {len(linhas)} Jobs não terminou no prazo")


def _em_lotes(linhas: Iterable[LinhaDoJob], tamanho: int) -> Iterator[list[LinhaDoJob]]:
    lote: list[LinhaDoJob] = []
    for linha in linhas:
        lote.append(linha)
        if len(lote) == tamanho:
            yield lote
            lote = []
    if lote:
        yield lote


def preencher(
    repositorio: RepositorioDeJobs, tabela: TabelaDeJobs, por_lote: int = JOBS_POR_MERGE
) -> int:
    """Grava uma linha por Job do repositório e devolve quantas. Passada única de linha de
    comando: lê o acervo inteiro; o MERGE pelo `id` faz repetir dar o mesmo resultado."""
    total = 0
    for lote in _em_lotes((linha_do_job(j) for j in repositorio.listar()), por_lote):
        tabela.gravar(lote)
        total += len(lote)
    return total


def main() -> int:
    config = ConfigDaTabelaDeJobs.do_ambiente(os.environ)
    total = preencher(
        RepositorioFirestore(cliente_do_firestore(config.projeto)),
        TabelaBigQuery(config, transporte_http(config.projeto)),
    )
    print(f"{total} Jobs gravados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
