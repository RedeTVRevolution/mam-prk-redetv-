"""A taxa de correção pré-calculada por dia (#455, parte 1 de 2).

A taxa (`api/taxa_de_correcao.py`) lia, a cada abertura do painel, as correções e a decupagem
inteira de cada vídeo revisado, um por vez. Aqui o mesmo cálculo roda uma vez por dia e o
resultado vai para a tabela `taxa_de_correcao_por_dia` do BigQuery: uma linha por dia, Job e
tipo de correção, com programa, versão do pipeline, `correcoes` e `itens`.

A regra é a de hoje, não uma cópia: `linhas_do_dia` chama `calcular_com_itens` sobre o período
`[dia, dia + 1)` em dia de São Paulo (o do período do painel, `api/qualidade_do_painel.py`), então vale o mesmo `_em_vigor_no_periodo`, a versão da
decupagem e só os Jobs concluídos. A diferença é a fonte dos itens: o objeto pequeno que a
decupagem ganha ao ser gravada (`api/itens_da_decupagem.py`), em vez do JSON inteiro.

O painel soma as correções e pega o máximo dos itens por Job antes de somar os Jobs (#509).
Reprocessar ou desfazer uma correção antiga muda itens e correções de dias passados.
O agendamento só refaz hoje e ontem: esses dias antigos exigem nova carga do histórico.
Na migração, `make preencher-taxa-diaria` substitui as linhas antigas sem Job nos dias refeitos.

Ambiente do comando: `GCP_PROJECT_ID`, `BUCKET_ACEITOS`, `BUCKET_DECUPAGENS`,
`BIGQUERY_DATASET`, `BIGQUERY_TABELA_DA_TAXA`, `BIGQUERY_REGIAO`.
"""

import json
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from google.api_core.exceptions import NotFound
from google.cloud.storage import Client as ClienteStorage

from api import log_estruturado
from api.bancos import cliente_do_firestore
from api.copia_bigquery import Transporte, parametro, transporte_http
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
from api.taxa_de_correcao import calcular_com_itens, modelo_da_decupagem

log = logging.getLogger(__name__)

DIAS_RECENTES = 2
DIAS_POR_MERGE = 100
# 8 MB para @linhas, com margem para a consulta e os demais parâmetros nos 10 MB do REST.
BYTES_POR_MERGE = 8_000_000
DIAS_DA_CARGA_INICIAL = 365
SAO_PAULO = ZoneInfo("America/Sao_Paulo")

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
    job_id: str
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
    return (
        datetime.combine(dia, time.min, SAO_PAULO).astimezone(UTC),
        datetime.combine(dia + timedelta(days=1), time.min, SAO_PAULO).astimezone(UTC),
    )


def linhas_do_dia(
    dia: date,
    repositorio: RepositorioDeJobs,
    itens: LeitorDeItens,
    correcoes: RepositorioDeCorrecoes,
    revisao: RepositorioDeRevisao,
    modelo_do_job: Callable[[str], dict[str, Any]] | None = None,
) -> list[LinhaDiaria]:
    inicio, fim = _periodo_do_dia(dia)
    return [
        LinhaDiaria(
            dia,
            job_id,
            x.programa,
            x.versao_pipeline,
            x.tipo,
            x.correcoes,
            x.itens,
        )
        for job_id, x in calcular_com_itens(
            repositorio,
            itens.ler_itens,
            correcoes,
            revisao,
            inicio,
            fim,
            modelo_do_job=modelo_do_job,
        )
    ]


def atualizar(
    dias: Sequence[date],
    repositorio: RepositorioDeJobs,
    itens: LeitorDeItens,
    correcoes: RepositorioDeCorrecoes,
    revisao: RepositorioDeRevisao,
    tabela: TabelaDaTaxa,
    modelo_do_job: Callable[[str], dict[str, Any]] | None = None,
) -> int:
    """Refaz os `dias` na tabela e devolve quantas linhas gravou."""
    linhas = [
        linha
        for dia in dias
        for linha in linhas_do_dia(
            dia, repositorio, itens, correcoes, revisao, modelo_do_job
        )
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
        por_dia: dict[date, list[LinhaDiaria]] = {}
        for linha in linhas:
            por_dia.setdefault(linha.dia, []).append(linha)
        lote: list[date] = []
        linhas_do_lote: list[LinhaDiaria] = []
        bytes_do_lote = 0
        for dia in dict.fromkeys(dias):
            do_dia = por_dia.get(dia, [])
            # Inclui os escapes no corpo HTTP; somar os dias superestima os colchetes.
            bytes_do_dia = len(
                json.dumps(json.dumps([_json_da_linha(x) for x in do_dia])).encode(
                    "utf-8"
                )
            )
            if lote and (
                len(lote) >= self._dias_por_merge
                or bytes_do_lote + bytes_do_dia > BYTES_POR_MERGE
            ):
                self._merge(lote, linhas_do_lote)
                lote, linhas_do_lote, bytes_do_lote = [], [], 0
            # ponytail: dia acima do teto vai sozinho; se ocorrer, migrar a carga para Storage.
            lote.append(dia)
            linhas_do_lote.extend(do_dia)
            bytes_do_lote += bytes_do_dia
        if lote:
            self._merge(lote, linhas_do_lote)

    def _merge(self, dias: Sequence[date], linhas: list[LinhaDiaria]) -> None:
        c = self._config
        tabela = f"`{c.projeto}.{c.dataset}.{c.tabela}`"
        consulta = f"""
MERGE {tabela} AS t
USING (
  SELECT
    DATE(JSON_VALUE(l, '$.dia')) AS dia,
    JSON_VALUE(l, '$.job_id') AS job_id,
    JSON_VALUE(l, '$.programa') AS programa,
    JSON_VALUE(l, '$.versao_pipeline') AS versao_pipeline,
    JSON_VALUE(l, '$.tipo') AS tipo,
    CAST(JSON_VALUE(l, '$.correcoes') AS INT64) AS correcoes,
    CAST(JSON_VALUE(l, '$.itens') AS INT64) AS itens
  FROM UNNEST(JSON_QUERY_ARRAY(PARSE_JSON(@linhas))) AS l
) AS s
ON t.dia IN UNNEST(@dias)
  AND t.dia = s.dia
  AND t.job_id = s.job_id
  AND t.programa IS NOT DISTINCT FROM s.programa
  AND t.versao_pipeline IS NOT DISTINCT FROM s.versao_pipeline
  AND t.tipo = s.tipo
WHEN MATCHED THEN UPDATE SET correcoes = s.correcoes, itens = s.itens
WHEN NOT MATCHED BY TARGET THEN INSERT (dia, job_id, programa, versao_pipeline, tipo, correcoes, itens)
VALUES (s.dia, s.job_id, s.programa, s.versao_pipeline, s.tipo, s.correcoes, s.itens)
WHEN NOT MATCHED BY SOURCE
  AND t.dia IN UNNEST(@dias)
THEN DELETE
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
                        json.dumps([_json_da_linha(x) for x in linhas]),
                    ),
                    # ARRAY<DATE> e não JSON: o BigQuery recusa subconsulta no ON do MERGE.
                    {
                        "name": "dias",
                        "parameterType": {
                            "type": "ARRAY",
                            "arrayType": {"type": "DATE"},
                        },
                        "parameterValue": {
                            "arrayValues": [{"value": d.isoformat()} for d in dias]
                        },
                    },
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
    banco = cliente_do_firestore(config.projeto)
    jobs = RepositorioFirestore(banco)
    itens = ItensNoStorage(cliente, os.environ["BUCKET_DECUPAGENS"])
    decupagens = DecupagensStorage(
        cliente, os.environ["BUCKET_ACEITOS"], os.environ["BUCKET_DECUPAGENS"]
    )
    if preenchendo:
        print(f"{preencher_itens(jobs, decupagens, itens)} contagens gravadas")
    gravadas = atualizar(
        dias_recentes(datetime.now(SAO_PAULO).date(), quantos),
        jobs,
        itens,
        RepositorioDeCorrecoesFirestore(banco),
        RepositorioDeRevisaoFirestore(banco),
        TabelaDaTaxaBigQuery(config, transporte_http(config.projeto)),
        lambda job_id: modelo_da_decupagem(decupagens, job_id),
    )
    print(f"{gravadas} linhas gravadas em {quantos} dias")
    return 0


if __name__ == "__main__":
    # Sem isto o Python cai no manejador padrão, em texto puro (#475).
    log_estruturado.configurar(logging.WARNING)
    sys.exit(main(sys.argv[1:]))
