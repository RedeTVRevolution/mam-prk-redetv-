"""A taxa de correção pré-calculada por dia (#455, parte 1 de 2).

A taxa (`api/taxa_de_correcao.py`) lia, a cada abertura do painel, as correções e a decupagem
inteira de cada vídeo revisado, um por vez. Aqui o mesmo cálculo roda uma vez por dia e o
resultado vai para a tabela `taxa_de_correcao_por_dia` do BigQuery: uma linha por dia, programa,
versão do pipeline e tipo de correção, com `correcoes` e `itens`. A segunda parte (#468) faz o
painel somar os dias.

A regra é a de hoje, não uma cópia: `linhas_do_dia` chama `calcular_com_itens` sobre o período
`[dia, dia + 1)` (UTC, como o painel), então vale o mesmo `_em_vigor_no_periodo`, a versão da
decupagem e só os Jobs concluídos. A diferença é a fonte dos itens: o objeto pequeno que a
decupagem ganha ao ser gravada (`api/itens_da_decupagem.py`), em vez do JSON inteiro.

Um vídeo revisado em dois dias do período tem os itens contados em cada um deles: somar os
dias dá mais itens que o cálculo de hoje sobre o período inteiro (as correções somam igual).
A tabela não tem o vídeo, então não dá para contar uma vez só; a parte 2 decide como o painel
lida com isso.

Ambiente do comando: `GCP_PROJECT_ID`, `BUCKET_ACEITOS`, `BUCKET_DECUPAGENS`,
`BIGQUERY_DATASET`, `BIGQUERY_TABELA_DA_TAXA`, `BIGQUERY_REGIAO`.
"""

import json
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol

from google.api_core.exceptions import NotFound
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.copia_bigquery import Transporte, _parametro, transporte_http
from api.correcoes import RepositorioDeCorrecoes
from api.itens_da_decupagem import (
    ItensDaDecupagem,
    contar_itens,
    objeto_dos_itens,
)
from api.jobs import RepositorioDeJobs, ServicoIndisponivel
from api.nuvem import (
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioDeRevisaoFirestore,
    RepositorioFirestore,
)
from api.reprocessar_versao import LeitorDeDecupagem
from api.revisao import RepositorioDeRevisao
from api.taxa_de_correcao import calcular_com_itens

log = logging.getLogger(__name__)

DIAS_RECENTES = 2
DIAS_POR_MERGE = 100
DIAS_DA_CARGA_INICIAL = 365

__all__ = [
    "ConfigDaTaxa",
    "ItensEmMemoria",
    "ItensNoStorage",
    "LinhaDiaria",
    "TabelaDaTaxaBigQuery",
    "TabelaDaTaxaEmMemoria",
    "atualizar",
    "dias_recentes",
    "linhas_do_dia",
    "main",
    "preencher_itens",
]


@dataclass(frozen=True)
class LinhaDiaria:
    dia: date
    programa: str | None
    versao_pipeline: str | None
    tipo: str
    correcoes: int
    itens: int


class LeitorDeItens(Protocol):
    def ler_itens(self, job_id: str) -> ItensDaDecupagem:
        """`ServicoIndisponivel` se a decupagem não tem contagem gravada."""


class GravadorDeItens(LeitorDeItens, Protocol):
    def gravar_itens(self, job_id: str, itens: ItensDaDecupagem) -> None: ...


class ItensEmMemoria:
    def __init__(self, itens: dict[str, ItensDaDecupagem] | None = None) -> None:
        self._itens = dict(itens or {})

    def ler_itens(self, job_id: str) -> ItensDaDecupagem:
        if job_id not in self._itens:
            raise ServicoIndisponivel
        return self._itens[job_id]

    def gravar_itens(self, job_id: str, itens: ItensDaDecupagem) -> None:
        self._itens[job_id] = itens

    def apagar(self, job_id: str) -> None:
        del self._itens[job_id]


class ItensNoStorage:
    """A contagem que a gravação da decupagem deixa no bucket das decupagens."""

    def __init__(self, cliente: ClienteStorage, bucket_de_decupagens: str) -> None:
        self._cliente = cliente
        self._decupagens = bucket_de_decupagens

    def ler_itens(self, job_id: str) -> ItensDaDecupagem:
        blob = self._cliente.bucket(self._decupagens).blob(objeto_dos_itens(job_id))
        try:
            return ItensDaDecupagem.do_json(blob.download_as_bytes())
        except NotFound as e:
            raise ServicoIndisponivel from e

    def gravar_itens(self, job_id: str, itens: ItensDaDecupagem) -> None:
        self._cliente.bucket(self._decupagens).blob(
            objeto_dos_itens(job_id)
        ).upload_from_string(itens.em_json(), content_type="application/json")


class TabelaDaTaxa(Protocol):
    def substituir(self, dias: Sequence[date], linhas: list[LinhaDiaria]) -> None:
        """Troca tudo o que a tabela tem desses dias pelas `linhas` (dias sem linha ficam
        vazios). Os outros dias não mudam; repetir dá o mesmo resultado."""


class TabelaDaTaxaEmMemoria:
    def __init__(self) -> None:
        self.linhas: list[LinhaDiaria] = []

    def substituir(self, dias: Sequence[date], linhas: list[LinhaDiaria]) -> None:
        self.linhas = [x for x in self.linhas if x.dia not in dias] + linhas


def _periodo_do_dia(dia: date) -> tuple[datetime, datetime]:
    inicio = datetime.combine(dia, time.min, UTC)
    return inicio, inicio + timedelta(days=1)


def linhas_do_dia(
    dia: date,
    repositorio: RepositorioDeJobs,
    itens: LeitorDeItens,
    correcoes: RepositorioDeCorrecoes,
    revisao: RepositorioDeRevisao,
) -> list[LinhaDiaria]:
    inicio, fim = _periodo_do_dia(dia)
    return [
        LinhaDiaria(
            dia,
            x.programa,
            x.versao_pipeline,
            x.tipo,
            x.correcoes,
            x.itens,
        )
        for x in calcular_com_itens(
            repositorio, itens.ler_itens, correcoes, revisao, inicio, fim
        )
    ]


def atualizar(
    dias: Sequence[date],
    repositorio: RepositorioDeJobs,
    itens: LeitorDeItens,
    correcoes: RepositorioDeCorrecoes,
    revisao: RepositorioDeRevisao,
    tabela: TabelaDaTaxa,
) -> int:
    """Refaz os `dias` na tabela e devolve quantas linhas gravou."""
    linhas = [
        linha
        for dia in dias
        for linha in linhas_do_dia(dia, repositorio, itens, correcoes, revisao)
    ]
    tabela.substituir(dias, linhas)
    return len(linhas)


def dias_recentes(hoje: date, quantos: int) -> list[date]:
    return [hoje - timedelta(days=n) for n in range(quantos - 1, -1, -1)]


def preencher_itens(
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    itens: GravadorDeItens,
) -> int:
    """Grava a contagem das decupagens de Jobs concluídos que não a têm (as anteriores ao
    #455) e devolve quantas gravou. Quem tem contagem não é lido de novo."""
    gravados = 0
    for job in repositorio.listar():
        if job.estado != "concluido":
            continue
        try:
            itens.ler_itens(job.id)
            continue
        except ServicoIndisponivel:
            pass
        try:
            contagem = contar_itens(b"".join(decupagens.abrir_decupagem(job.id)))
        except (ServicoIndisponivel, ValueError, KeyError, TypeError):
            log.warning("decupagem de %s não lida: sem contagem", job.id)
            continue
        itens.gravar_itens(job.id, contagem)
        gravados += 1
    return gravados


@dataclass(frozen=True)
class ConfigDaTaxa:
    projeto: str
    dataset: str
    regiao: str
    tabela: str

    @classmethod
    def do_ambiente(cls, ambiente: Any) -> "ConfigDaTaxa":
        return cls(
            projeto=ambiente["GCP_PROJECT_ID"],
            dataset=ambiente["BIGQUERY_DATASET"],
            regiao=ambiente["BIGQUERY_REGIAO"],
            tabela=ambiente["BIGQUERY_TABELA_DA_TAXA"],
        )


def _json_da_linha(linha: LinhaDiaria) -> dict[str, Any]:
    return {**asdict(linha), "dia": linha.dia.isoformat()}


class TabelaDaTaxaBigQuery:
    """A tabela real: um MERGE por lote de dias troca as linhas deles (as que sumiram saem
    pelo `WHEN NOT MATCHED BY SOURCE`), numa só instrução."""

    def __init__(
        self,
        config: ConfigDaTaxa,
        transporte: Transporte,
        dias_por_merge: int = DIAS_POR_MERGE,
    ) -> None:
        self._config = config
        self._transporte = transporte
        self._dias_por_merge = dias_por_merge

    def substituir(self, dias: Sequence[date], linhas: list[LinhaDiaria]) -> None:
        for i in range(0, len(dias), self._dias_por_merge):
            lote = dias[i : i + self._dias_por_merge]
            self._merge(lote, [x for x in linhas if x.dia in lote])

    def _merge(self, dias: Sequence[date], linhas: list[LinhaDiaria]) -> None:
        c = self._config
        tabela = f"`{c.projeto}.{c.dataset}.{c.tabela}`"
        consulta = f"""
MERGE {tabela} AS t
USING (
  SELECT
    DATE(JSON_VALUE(l, '$.dia')) AS dia,
    JSON_VALUE(l, '$.programa') AS programa,
    JSON_VALUE(l, '$.versao_pipeline') AS versao_pipeline,
    JSON_VALUE(l, '$.tipo') AS tipo,
    CAST(JSON_VALUE(l, '$.correcoes') AS INT64) AS correcoes,
    CAST(JSON_VALUE(l, '$.itens') AS INT64) AS itens
  FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@linhas))) AS l
) AS s
ON t.dia IN UNNEST(ARRAY(SELECT DATE(d) FROM UNNEST(JSON_VALUE_ARRAY(PARSE_JSON(@dias))) AS d))
  AND t.dia = s.dia
  AND t.programa IS NOT DISTINCT FROM s.programa
  AND t.versao_pipeline IS NOT DISTINCT FROM s.versao_pipeline
  AND t.tipo = s.tipo
WHEN MATCHED THEN UPDATE SET correcoes = s.correcoes, itens = s.itens
WHEN NOT MATCHED BY TARGET THEN INSERT (dia, programa, versao_pipeline, tipo, correcoes, itens)
VALUES (s.dia, s.programa, s.versao_pipeline, s.tipo, s.correcoes, s.itens)
WHEN NOT MATCHED BY SOURCE
  AND t.dia IN UNNEST(ARRAY(SELECT DATE(d) FROM UNNEST(JSON_VALUE_ARRAY(PARSE_JSON(@dias))) AS d))
THEN DELETE
"""
        resposta = self._transporte(
            {
                "query": consulta,
                "useLegacySql": False,
                "location": c.regiao,
                "timeoutMs": 120_000,
                "queryParameters": [
                    _parametro(
                        "linhas",
                        json.dumps([_json_da_linha(x) for x in linhas]),
                    ),
                    _parametro("dias", json.dumps([d.isoformat() for d in dias])),
                ],
            }
        )
        if not resposta.get("jobComplete", False):
            raise RuntimeError(
                f"a troca dos dias {dias[0]} a {dias[-1]} não terminou no prazo"
            )


def main(argumentos: list[str]) -> int:
    """Sem argumentos refaz hoje e ontem (a execução agendada). `DIAS=<n>` refaz os últimos
    n dias; `PREENCHER` antes grava a contagem das decupagens que ainda não têm e refaz o
    último ano (`make preencher-taxa-diaria`)."""
    preenchendo = "PREENCHER" in argumentos
    numeros = [a for a in argumentos if a.isdigit()]
    quantos = (
        int(numeros[0])
        if numeros
        else DIAS_DA_CARGA_INICIAL
        if preenchendo
        else DIAS_RECENTES
    )
    config = ConfigDaTaxa.do_ambiente(os.environ)
    cliente = ClienteStorage(project=config.projeto)
    banco = firestore.Client(project=config.projeto)
    jobs = RepositorioFirestore(banco)
    itens = ItensNoStorage(cliente, os.environ["BUCKET_DECUPAGENS"])
    if preenchendo:
        decupagens = DecupagensStorage(
            cliente, os.environ["BUCKET_ACEITOS"], os.environ["BUCKET_DECUPAGENS"]
        )
        print(f"{preencher_itens(jobs, decupagens, itens)} contagens gravadas")
    gravadas = atualizar(
        dias_recentes(datetime.now(UTC).date(), quantos),
        jobs,
        itens,
        RepositorioDeCorrecoesFirestore(banco),
        RepositorioDeRevisaoFirestore(banco),
        TabelaDaTaxaBigQuery(config, transporte_http(config.projeto)),
    )
    print(f"{gravadas} linhas gravadas em {quantos} dias")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
