"""Relatório de tempo de tela por pessoa (#266): `GET /v1/relatorios/tempo-de-tela`.

Lê da cópia no BigQuery (#260) as linhas `aparicao`, `mencao_na_fala` e `mencao_no_texto`.
Só a aparição (a pessoa visível) soma tempo de tela; as menções entram só como contagem.
Aparições da mesma pessoa no mesmo vídeo que se sobrepõem ou se tocam viram uma só.
A consulta filtra no BigQuery por programa e data de exibição e também soma lá (#363):
a união dos intervalos é feita em SQL (janelas, "gaps and islands") e o BigQuery devolve
uma linha por pessoa e vídeo. O Python só junta as linhas na resposta. Sem teto de linhas
brutas; o que resta é o do resultado somado (uma resposta de até 10 MB).
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.copia_bigquery import (
    TIPOS_DAS_PESSOAS,
    ConfigDoBigQuery,
    CopiaEmMemoria,
    Transporte,
)
from api.jobs import RepositorioDeJobs
from api.relatorios import (
    PodeVerORelatorio,
    confere_o_pedido,
    config_e_transporte_do_ambiente,
    consultar_no_bigquery,
    csv_em_texto,
    linhas_da_copia,
    ou_503,
    poe_o_nome_dos_videos,
    resposta_em_csv,
)

TIPOS_DO_RELATORIO = TIPOS_DAS_PESSOAS
COLUNAS_DO_CSV = (
    "pessoa_id",
    "nome",
    "tempo_de_tela_ms",
    "videos",
    "aparicoes",
    "mencoes_na_fala",
    "mencoes_no_texto",
)


@dataclass(frozen=True)
class MomentoDaPessoa:
    job_id: str
    pessoa_id: str
    nome: str
    tipo: str
    inicio_ms: int
    fim_ms: int


@dataclass(frozen=True)
class PessoaNoVideo:
    """A soma de uma pessoa num vídeo: o que o SQL devolve, uma linha por par."""

    job_id: str
    pessoa_id: str
    nomes: dict[str, int]  # o nome e em quantas linhas da cópia ele aparece
    tempo_de_tela_ms: int
    aparicoes: int  # depois de unir as sobrepostas
    mencoes_na_fala: int
    mencoes_no_texto: int


class ConsultaDeMomentos(Protocol):
    def somas(
        self, programa: str | None, desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        """Uma soma por pessoa e vídeo; `desde` e `ate` são datas de exibição, inclusive."""


def _uniao(intervalos: list[tuple[int, int]]) -> list[tuple[int, int]]:
    unidos: list[tuple[int, int]] = []
    for inicio, fim in sorted(intervalos):
        if unidos and inicio <= unidos[-1][1]:
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], fim))
        else:
            unidos.append((inicio, fim))
    return unidos


def somar(momentos: list[MomentoDaPessoa]) -> list[PessoaNoVideo]:
    """A soma em Python do que `SOMA_EM_SQL` faz no BigQuery (o dublê e a referência)."""
    por_par: dict[tuple[str, str], list[MomentoDaPessoa]] = defaultdict(list)
    for m in momentos:
        por_par[(m.job_id, m.pessoa_id)].append(m)
    somas: list[PessoaNoVideo] = []
    for (job_id, pessoa_id), do_video in por_par.items():
        aparicoes = _uniao(
            [(m.inicio_ms, m.fim_ms) for m in do_video if m.tipo == "aparicao"]
        )
        somas.append(
            PessoaNoVideo(
                job_id=job_id,
                pessoa_id=pessoa_id,
                nomes=dict(Counter(m.nome for m in do_video)),
                tempo_de_tela_ms=sum(fim - ini for ini, fim in aparicoes),
                aparicoes=len(aparicoes),
                mencoes_na_fala=sum(m.tipo == "mencao_na_fala" for m in do_video),
                mencoes_no_texto=sum(m.tipo == "mencao_no_texto" for m in do_video),
            )
        )
    return somas


class ConsultaEmMemoria:
    """Dublê da consulta: os mesmos filtros e a mesma soma sobre a cópia em memória."""

    def __init__(self, copia: CopiaEmMemoria) -> None:
        self._copia = copia

    def momentos(
        self, programa: str | None, desde: date | None, ate: date | None
    ) -> list[MomentoDaPessoa]:
        return [
            MomentoDaPessoa(x.job_id, p.id, p.nome, x.tipo, x.inicio_ms, x.fim_ms)
            for x in linhas_da_copia(
                self._copia, TIPOS_DO_RELATORIO, programa, desde, ate
            )
            for p in x.pessoas
        ]

    def somas(
        self, programa: str | None, desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        return somar(self.momentos(programa, desde, ate))


# A união dos intervalos de aparição por pessoa e vídeo, sobre a CTE `base`. Só SQL
# portável (janelas com ROWS), para o teste rodar o mesmo texto num SQLite e comparar com
# `_uniao`. Um intervalo abre uma ilha nova quando começa depois do maior fim já visto
# (começar no fim dele cola, como em `_uniao`).
UNIAO_EM_SQL = """aparicoes AS (
  SELECT job_id, pessoa_id, inicio_ms, fim_ms,
    MAX(fim_ms) OVER (
      PARTITION BY job_id, pessoa_id ORDER BY inicio_ms, fim_ms
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) AS fim_anterior
  FROM base
  WHERE tipo = 'aparicao'
),
com_ilha AS (
  SELECT job_id, pessoa_id, inicio_ms, fim_ms,
    SUM(CASE WHEN fim_anterior IS NULL OR inicio_ms > fim_anterior THEN 1 ELSE 0 END) OVER (
      PARTITION BY job_id, pessoa_id ORDER BY inicio_ms, fim_ms
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS ilha
  FROM aparicoes
),
unidas AS (
  SELECT job_id, pessoa_id, MIN(inicio_ms) AS inicio_ms, MAX(fim_ms) AS fim_ms
  FROM com_ilha
  GROUP BY job_id, pessoa_id, ilha
)"""

# O que vem depois de `WITH base AS (...)`: uma linha por pessoa e vídeo, com o tempo
# das aparições unidas, as contagens e os nomes (com quantas linhas cada um tem).
SOMA_EM_SQL = f""", {UNIAO_EM_SQL},
tempo AS (
  SELECT job_id, pessoa_id, SUM(fim_ms - inicio_ms) AS tempo_ms, COUNT(*) AS aparicoes
  FROM unidas
  GROUP BY job_id, pessoa_id
),
contagens AS (
  SELECT job_id, pessoa_id,
    COUNTIF(tipo = 'mencao_na_fala') AS na_fala,
    COUNTIF(tipo = 'mencao_no_texto') AS no_texto
  FROM base
  GROUP BY job_id, pessoa_id
),
nomes AS (
  SELECT job_id, pessoa_id, TO_JSON_STRING(ARRAY_AGG(STRUCT(nome, linhas))) AS nomes
  FROM (
    SELECT job_id, pessoa_id, nome, COUNT(*) AS linhas
    FROM base
    GROUP BY job_id, pessoa_id, nome
  )
  GROUP BY job_id, pessoa_id
)
SELECT c.job_id, c.pessoa_id, IFNULL(t.tempo_ms, 0), IFNULL(t.aparicoes, 0),
  c.na_fala, c.no_texto, n.nomes
FROM contagens AS c
LEFT JOIN tempo AS t ON t.job_id = c.job_id AND t.pessoa_id = c.pessoa_id
JOIN nomes AS n ON n.job_id = c.job_id AND n.pessoa_id = c.pessoa_id"""


class ConsultaBigQuery:
    """A consulta real: REST com o mesmo transporte da cópia."""

    def __init__(self, config: ConfigDoBigQuery, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def somas(
        self, programa: str | None, desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        linhas = consultar_no_bigquery(
            self._config,
            self._transporte,
            colunas=(
                "t.job_id, p.id AS pessoa_id, COALESCE(p.nome, '') AS nome, "
                "t.tipo, t.inicio_ms, t.fim_ms"
            ),
            tipos=TIPOS_DO_RELATORIO,
            programa=programa,
            desde=desde,
            ate=ate,
            unnest_das_pessoas=True,
            condicoes=["p.id IS NOT NULL"],
            depois_da_base=SOMA_EM_SQL,
        )
        return [
            PessoaNoVideo(
                job_id=v[0],
                pessoa_id=v[1],
                nomes={n["nome"]: int(n["linhas"]) for n in json.loads(v[6])},
                tempo_de_tela_ms=int(v[2]),
                aparicoes=int(v[3]),
                mencoes_na_fala=int(v[4]),
                mencoes_no_texto=int(v[5]),
            )
            for v in linhas
        ]


def consulta_do_ambiente(ambiente: Any) -> ConsultaBigQuery | None:
    """A consulta configurada, ou `None` se o ambiente não diz onde a cópia mora."""
    onde = config_e_transporte_do_ambiente(ambiente)
    return ConsultaBigQuery(*onde) if onde else None


class VideoDaPessoa(BaseModel):
    job_id: str
    nome: str | None = None
    tempo_de_tela_ms: int
    aparicoes: int
    mencoes_na_fala: int
    mencoes_no_texto: int


class PessoaNoRelatorio(BaseModel):
    pessoa_id: str
    nome: str
    tempo_de_tela_ms: int
    videos: int  # os vídeos em que aparece (quem só foi citado não conta)
    aparicoes: int
    mencoes_na_fala: int
    mencoes_no_texto: int
    por_video: list[VideoDaPessoa]


class RelatorioDeTempoDeTela(BaseModel):
    programa: str | None
    desde: date | None
    ate: date | None
    pessoas: list[PessoaNoRelatorio]


def relatorio(somas: list[PessoaNoVideo]) -> list[PessoaNoRelatorio]:
    """Uma linha por pessoa, do maior tempo de tela para o menor.

    A pessoa é o id do catálogo; o nome é o que mais aparece nas linhas dela (um vídeo
    copiado antes de uma correção de grafia não parte a pessoa em duas).
    """
    por_pessoa: dict[str, list[PessoaNoVideo]] = defaultdict(list)
    for s in somas:
        por_pessoa[s.pessoa_id].append(s)
    pessoas: list[PessoaNoRelatorio] = []
    for pessoa_id, dela in por_pessoa.items():
        contagem: Counter[str] = Counter()
        for s in dela:
            contagem.update(s.nomes)
        nome = min(contagem, key=lambda n: (-contagem[n], n))
        videos = [
            VideoDaPessoa(
                job_id=s.job_id,
                tempo_de_tela_ms=s.tempo_de_tela_ms,
                aparicoes=s.aparicoes,
                mencoes_na_fala=s.mencoes_na_fala,
                mencoes_no_texto=s.mencoes_no_texto,
            )
            for s in dela
        ]
        videos.sort(key=lambda v: (-v.tempo_de_tela_ms, v.job_id))
        pessoas.append(
            PessoaNoRelatorio(
                pessoa_id=pessoa_id,
                nome=nome,
                tempo_de_tela_ms=sum(v.tempo_de_tela_ms for v in videos),
                videos=sum(v.aparicoes > 0 for v in videos),
                aparicoes=sum(v.aparicoes for v in videos),
                mencoes_na_fala=sum(v.mencoes_na_fala for v in videos),
                mencoes_no_texto=sum(v.mencoes_no_texto for v in videos),
                por_video=videos,
            )
        )
    pessoas.sort(key=lambda p: (-p.tempo_de_tela_ms, p.nome, p.pessoa_id))
    return pessoas


def em_csv(pessoas: list[PessoaNoRelatorio]) -> str:
    return csv_em_texto(
        COLUNAS_DO_CSV,
        [
            [
                p.pessoa_id,
                p.nome,
                p.tempo_de_tela_ms,
                p.videos,
                p.aparicoes,
                p.mencoes_na_fala,
                p.mencoes_no_texto,
            ]
            for p in pessoas
        ],
    )


def criar_rotas_do_tempo_de_tela(
    consulta: ConsultaDeMomentos | None, repositorio: RepositorioDeJobs
) -> APIRouter:
    rotas = APIRouter(prefix="/relatorios")

    @rotas.get("/tempo-de-tela", response_model=RelatorioDeTempoDeTela)
    def tempo_de_tela(
        _pessoa: PodeVerORelatorio,
        programa: Annotated[str | None, Query(max_length=100)] = None,
        desde: date | None = None,
        ate: date | None = None,
        formato: Literal["json", "csv"] = "json",
    ) -> Any:
        """`desde` e `ate` são datas de exibição, as duas inclusive; sem programa
        (ou com `programa=` vazio), todos."""
        programa = programa or None
        fonte = confere_o_pedido(consulta, desde, ate)
        pessoas = ou_503(lambda: relatorio(fonte.somas(programa, desde, ate)))
        if formato == "csv":
            return resposta_em_csv(em_csv(pessoas), "tempo-de-tela.csv")
        poe_o_nome_dos_videos((v for p in pessoas for v in p.por_video), repositorio)
        return RelatorioDeTempoDeTela(
            programa=programa, desde=desde, ate=ate, pessoas=pessoas
        )

    return rotas
