"""Relatório de tempo de tela por pessoa (#266): `GET /v1/relatorios/tempo-de-tela`.

Lê da cópia no BigQuery (#260) as linhas `aparicao`, `mencao_na_fala` e `mencao_no_texto`.
Só a aparição (a pessoa visível) soma tempo de tela; as menções entram só como contagem.
Aparições da mesma pessoa no mesmo vídeo que se sobrepõem ou se tocam viram uma só.
A consulta filtra no BigQuery por programa e data de exibição e também soma lá (#363):
a união dos intervalos é feita em SQL (janelas, "gaps and islands") e o BigQuery devolve
uma linha por pessoa e vídeo, em quantas páginas precisar. O Python só junta as linhas na
resposta. Sem teto de linhas brutas; o que resta é o resultado somado caber na memória da
instância.
"""

import json
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.cache_curto import CacheCurto
from api.catalogo import Catalogo
from api.copia_bigquery import (
    TIPOS_DAS_PESSOAS,
    ConfigDoBigQuery,
    CopiaEmMemoria,
    Transporte,
    _parametro,
)
from api.csv_seguro import csv_em_texto
from api.jobs import RepositorioDeJobs
from api.periodo_padrao import Periodo, agora_em_sao_paulo, dependencia_do_periodo
from api.relatorios import (
    LIMITE_DA_PAGINA,
    PodeVerORelatorio,
    confere_o_pedido,
    config_e_transporte_do_ambiente,
    consultar_no_bigquery,
    linhas_da_copia,
    ou_503,
    parametros_da_pagina,
    poe_o_nome_dos_videos,
    posicao_do_cursor,
    recorta,
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

    def ranking(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        depois: int,
        limite: int,
    ) -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
        """Até `limite + 1` pessoas a partir da posição `depois`, do maior tempo para o
        menor (o id desempata), e os totais do período."""

    def videos_da_pessoa(
        self,
        pessoa_id: str,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        depois: int,
        limite: int,
    ) -> "list[VideoDaPessoa]":
        """Até `limite + 1` vídeos da pessoa a partir da posição `depois`, na ordem do
        relatório."""


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

    def ranking(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        depois: int,
        limite: int,
    ) -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
        return ranking_em_python(self.somas(programa, desde, ate), depois, limite)

    def videos_da_pessoa(
        self,
        pessoa_id: str,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        depois: int,
        limite: int,
    ) -> "list[VideoDaPessoa]":
        somas = self.somas(programa, desde, ate)
        return videos_em_python(somas, pessoa_id, depois, limite)


def ranking_em_python(
    somas: list[PessoaNoVideo], depois: int, limite: int
) -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
    """O que `RANKING_EM_SQL` faz no BigQuery (o dublê e a referência)."""
    pessoas = relatorio(somas)
    total = TotalDoTempoDeTela(
        pessoas=len(pessoas),
        tempo_de_tela_ms=sum(p.tempo_de_tela_ms for p in pessoas),
        videos=len({v.job_id for p in pessoas for v in p.por_video if v.aparicoes}),
        aparicoes=sum(p.aparicoes for p in pessoas),
        mencoes_na_fala=sum(p.mencoes_na_fala for p in pessoas),
        mencoes_no_texto=sum(p.mencoes_no_texto for p in pessoas),
    )
    pessoas.sort(key=lambda p: (-p.tempo_de_tela_ms, p.pessoa_id))
    pagina = pessoas[depois : depois + limite + 1]
    return [
        PessoaResumida(**p.model_dump(exclude={"por_video"})) for p in pagina
    ], total


def videos_em_python(
    somas: list[PessoaNoVideo], pessoa_id: str, depois: int, limite: int
) -> "list[VideoDaPessoa]":
    """O que `VIDEOS_DA_PESSOA_EM_SQL` faz no BigQuery (o dublê e a referência)."""
    dela = [s for s in somas if s.pessoa_id == pessoa_id]
    por_video = relatorio(dela)[0].por_video if dela else []
    return por_video[depois : depois + limite + 1]


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

# Os nomes da pessoa no vídeo, com quantas linhas cada um tem, num texto JSON. É o único
# trecho só do BigQuery: o teste troca por `json_group_array` e roda o resto num SQLite.
NOMES_EM_JSON = "TO_JSON_STRING(ARRAY_AGG(STRUCT(nome, linhas)))"

# O que vem depois de `WITH base AS (...)`: uma linha por pessoa e vídeo, com o tempo
# das aparições unidas, as contagens e os nomes. As contagens e os nomes saem de uma
# passada só pela `base` (cada CTE que a lê é mais uma leitura da tabela).
_CTES_DA_SOMA = f""", {UNIAO_EM_SQL},
tempo AS (
  SELECT job_id, pessoa_id, SUM(fim_ms - inicio_ms) AS tempo_ms, COUNT(*) AS aparicoes
  FROM unidas
  GROUP BY job_id, pessoa_id
),
por_nome AS (
  SELECT job_id, pessoa_id, nome, COUNT(*) AS linhas,
    SUM(CASE WHEN tipo = 'mencao_na_fala' THEN 1 ELSE 0 END) AS na_fala,
    SUM(CASE WHEN tipo = 'mencao_no_texto' THEN 1 ELSE 0 END) AS no_texto
  FROM base
  GROUP BY job_id, pessoa_id, nome
),
contagens AS (
  SELECT job_id, pessoa_id, SUM(na_fala) AS na_fala, SUM(no_texto) AS no_texto,
    {NOMES_EM_JSON} AS nomes
  FROM por_nome
  GROUP BY job_id, pessoa_id
)"""
_SELECT_POR_VIDEO = """SELECT c.job_id, c.pessoa_id, IFNULL(t.tempo_ms, 0) AS tempo_ms,
  IFNULL(t.aparicoes, 0) AS aparicoes, c.na_fala, c.no_texto, c.nomes
FROM contagens AS c
LEFT JOIN tempo AS t ON t.job_id = c.job_id AND t.pessoa_id = c.pessoa_id"""
SOMA_EM_SQL = f"{_CTES_DA_SOMA}\n{_SELECT_POR_VIDEO}"

# A página do ranking (o relatório com `limite`): a mesma soma, agrupada por pessoa no
# BigQuery, com o nome que mais aparece (no empate, o menor), a posição na ordem do tempo
# (o id desempata) e os totais do período em cada linha. Só volta a página.
RANKING_EM_SQL = f"""{_CTES_DA_SOMA},
por_video AS (
{_SELECT_POR_VIDEO}
),
por_pessoa AS (
  SELECT pessoa_id, SUM(tempo_ms) AS tempo_ms,
    SUM(CASE WHEN aparicoes > 0 THEN 1 ELSE 0 END) AS videos,
    SUM(aparicoes) AS aparicoes, SUM(na_fala) AS na_fala, SUM(no_texto) AS no_texto
  FROM por_video
  GROUP BY pessoa_id
),
linhas_do_nome AS (
  SELECT pessoa_id, nome, SUM(linhas) AS linhas FROM por_nome GROUP BY pessoa_id, nome
),
nome_da_pessoa AS (
  SELECT pessoa_id, nome FROM (
    SELECT pessoa_id, nome,
      ROW_NUMBER() OVER (PARTITION BY pessoa_id ORDER BY linhas DESC, nome) AS ordem
    FROM linhas_do_nome
  ) AS nomes WHERE ordem = 1
),
ranking AS (
  SELECT pessoa_id, tempo_ms, videos, aparicoes, na_fala, no_texto,
    ROW_NUMBER() OVER (ORDER BY tempo_ms DESC, pessoa_id) AS posicao,
    COUNT(*) OVER () AS total_pessoas, SUM(tempo_ms) OVER () AS total_tempo,
    SUM(aparicoes) OVER () AS total_aparicoes, SUM(na_fala) OVER () AS total_na_fala,
    SUM(no_texto) OVER () AS total_no_texto
  FROM por_pessoa
)
SELECT r.pessoa_id, n.nome, r.tempo_ms, r.videos, r.aparicoes, r.na_fala, r.no_texto,
  r.total_pessoas, r.total_tempo,
  (SELECT COUNT(DISTINCT job_id) FROM por_video WHERE aparicoes > 0) AS total_videos,
  r.total_aparicoes, r.total_na_fala, r.total_no_texto
FROM ranking AS r
JOIN nome_da_pessoa AS n ON n.pessoa_id = r.pessoa_id
WHERE r.posicao > @posicao_de AND r.posicao <= @posicao_ate
ORDER BY r.posicao"""

# Os vídeos de uma pessoa (a base já vem só com ela), na ordem do relatório, só a página.
VIDEOS_DA_PESSOA_EM_SQL = f"""{_CTES_DA_SOMA},
por_video AS (
{_SELECT_POR_VIDEO}
)
SELECT job_id, tempo_ms, aparicoes, na_fala, no_texto FROM (
  SELECT job_id, tempo_ms, aparicoes, na_fala, no_texto,
    ROW_NUMBER() OVER (ORDER BY tempo_ms DESC, job_id) AS posicao
  FROM por_video
) AS videos
WHERE posicao > @posicao_de AND posicao <= @posicao_ate
ORDER BY posicao"""


def pessoa_no_video(v: Sequence[Any]) -> PessoaNoVideo:
    """Uma linha do `SOMA_EM_SQL`, na ordem das colunas do SELECT final."""
    return PessoaNoVideo(
        job_id=v[0],
        pessoa_id=v[1],
        nomes={n["nome"]: int(n["linhas"]) for n in json.loads(v[6])},
        tempo_de_tela_ms=int(v[2]),
        aparicoes=int(v[3]),
        mencoes_na_fala=int(v[4]),
        mencoes_no_texto=int(v[5]),
    )


class ConsultaBigQuery:
    """A consulta real: REST com o mesmo transporte da cópia."""

    def __init__(self, config: ConfigDoBigQuery, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def _consultar(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        depois_da_base: str,
        condicoes: Sequence[str] = (),
        parametros: Sequence[dict[str, Any]] = (),
    ) -> list[list[Any]]:
        return consultar_no_bigquery(
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
            condicoes=["p.id IS NOT NULL", *condicoes],
            parametros=parametros,
            depois_da_base=depois_da_base,
        )

    def somas(
        self, programa: str | None, desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        linhas = self._consultar(programa, desde, ate, SOMA_EM_SQL)
        return [pessoa_no_video(v) for v in linhas]

    def ranking(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        depois: int,
        limite: int,
    ) -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
        linhas = self._consultar(
            programa,
            desde,
            ate,
            RANKING_EM_SQL,
            parametros=parametros_da_pagina(depois, limite),
        )
        return pagina_do_ranking(linhas)

    def videos_da_pessoa(
        self,
        pessoa_id: str,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        depois: int,
        limite: int,
    ) -> "list[VideoDaPessoa]":
        linhas = self._consultar(
            programa,
            desde,
            ate,
            VIDEOS_DA_PESSOA_EM_SQL,
            condicoes=["p.id = @pessoa_id"],
            parametros=[
                _parametro("pessoa_id", pessoa_id),
                *parametros_da_pagina(depois, limite),
            ],
        )
        return [video_da_pessoa(v) for v in linhas]


def pagina_do_ranking(
    linhas: Sequence[Sequence[Any]],
) -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
    """As linhas do `RANKING_EM_SQL`, na ordem das colunas do SELECT. Página vazia (um
    cursor além do fim) não traz os totais: vêm zerados."""
    pessoas = [
        PessoaResumida(
            pessoa_id=v[0],
            nome=v[1],
            tempo_de_tela_ms=int(v[2]),
            videos=int(v[3]),
            aparicoes=int(v[4]),
            mencoes_na_fala=int(v[5]),
            mencoes_no_texto=int(v[6]),
        )
        for v in linhas
    ]
    totais = [int(t) for t in linhas[0][7:13]] if linhas else [0] * 6
    return pessoas, TotalDoTempoDeTela(
        **dict(zip(TotalDoTempoDeTela.model_fields, totais, strict=True))
    )


def video_da_pessoa(v: Sequence[Any]) -> "VideoDaPessoa":
    """Uma linha do `VIDEOS_DA_PESSOA_EM_SQL`, na ordem das colunas do SELECT."""
    return VideoDaPessoa(
        job_id=v[0],
        tempo_de_tela_ms=int(v[1]),
        aparicoes=int(v[2]),
        mencoes_na_fala=int(v[3]),
        mencoes_no_texto=int(v[4]),
    )


class ConsultaComCache:
    """A soma por filtro, calculada uma vez e lembrada (#453): o ranking inteiro, a página, a
    pessoa expandida e o CSV saem dela, sem consultar o BigQuery de novo."""

    def __init__(self, consulta: ConsultaDeMomentos, cache: CacheCurto) -> None:
        self._consulta = consulta
        self._cache = cache

    def somas(
        self, programa: str | None, desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        return self._cache.obter(
            ("tempo-de-tela", programa, desde, ate),
            lambda: self._consulta.somas(programa, desde, ate),
        )

    def _ranking_inteiro(
        self, programa: str | None, desde: date | None, ate: date | None
    ) -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
        def calcular() -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
            somas = self.somas(programa, desde, ate)
            return ranking_em_python(somas, 0, len(somas))

        return self._cache.obter(
            ("tempo-de-tela-ranking", programa, desde, ate), calcular
        )

    def ranking(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        depois: int,
        limite: int,
    ) -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
        todas, total = self._ranking_inteiro(programa, desde, ate)
        return todas[depois : depois + limite + 1], total

    def videos_da_pessoa(
        self,
        pessoa_id: str,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        depois: int,
        limite: int,
    ) -> "list[VideoDaPessoa]":
        somas = self.somas(programa, desde, ate)
        return videos_em_python(somas, pessoa_id, depois, limite)


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


class PessoaResumida(BaseModel):
    pessoa_id: str
    nome: str
    tempo_de_tela_ms: int
    videos: int  # os vídeos em que aparece (quem só foi citado não conta)
    aparicoes: int
    mencoes_na_fala: int
    mencoes_no_texto: int


class PessoaNoRelatorio(PessoaResumida):
    por_video: list[VideoDaPessoa]


class TotalDoTempoDeTela(BaseModel):
    """O período inteiro, não só a página: os números dos cartões. `videos` são os vídeos
    com alguma aparição."""

    pessoas: int
    tempo_de_tela_ms: int
    videos: int
    aparicoes: int
    mencoes_na_fala: int
    mencoes_no_texto: int


class RankingDoTempoDeTela(BaseModel):
    """O relatório com `limite`: uma página das pessoas, sem os vídeos de cada uma."""

    programa: str | None
    desde: date | None
    ate: date | None
    total: TotalDoTempoDeTela
    pessoas: list[PessoaResumida]


class RelatorioDeTempoDeTela(BaseModel):
    programa: str | None
    desde: date | None
    ate: date | None
    pessoas: list[PessoaNoRelatorio]


def relatorio(somas: list[PessoaNoVideo]) -> list[PessoaNoRelatorio]:
    """Uma linha por pessoa, do maior tempo de tela para o menor.

    A pessoa é o id do catálogo; o nome é o que mais aparece nas linhas dela (um vídeo
    copiado antes de uma correção de grafia não parte a pessoa em duas). A rota troca
    esse nome pelo do catálogo (`com_nomes_do_catalogo`, #417).
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


def com_nomes_do_catalogo[P: PessoaResumida](
    pessoas: list[P], catalogo: Catalogo | None
) -> list[P]:
    """O nome de cada pessoa vem do catálogo, numa leitura em lote (#417): a cópia no
    BigQuery não guarda o nome, então renomear no catálogo vale na hora. Quem o catálogo
    não conhece fica com o que a cópia trouxe. Devolve cópias: o ranking guardado no cache
    não muda."""
    if catalogo is None or not pessoas:
        return pessoas
    do_catalogo = catalogo.obter_varios(p.pessoa_id for p in pessoas)
    return [
        p.model_copy(update={"nome": do_catalogo[p.pessoa_id].nome})
        if p.pessoa_id in do_catalogo
        else p
        for p in pessoas
    ]


def criar_rotas_do_tempo_de_tela(
    consulta: ConsultaDeMomentos | None,
    repositorio: RepositorioDeJobs,
    relogio: Callable[[], datetime] = agora_em_sao_paulo,
    catalogo: Catalogo | None = None,
) -> APIRouter:
    rotas = APIRouter(prefix="/relatorios")
    no_periodo = dependencia_do_periodo(relogio)

    @rotas.get(
        "/tempo-de-tela",
        response_model=RelatorioDeTempoDeTela | RankingDoTempoDeTela,
    )
    def tempo_de_tela(
        _pessoa: PodeVerORelatorio,
        periodo: Annotated[Periodo, Depends(no_periodo)],
        programa: Annotated[str | None, Query(max_length=100)] = None,
        formato: Literal["json", "csv"] = "json",
        limite: Annotated[int | None, Query(ge=1, le=LIMITE_DA_PAGINA)] = None,
        cursor: str | None = None,
    ) -> Any:
        """`desde` e `ate` são datas de exibição, as duas inclusive; sem programa
        (ou com `programa=` vazio), todos. Com `limite`, uma página do ranking (sem os
        vídeos, com os totais do período) e o cursor da próxima em `X-Proximo-Cursor`;
        os vídeos de uma pessoa ficam em `/tempo-de-tela/videos`. O CSV vem sempre
        inteiro."""
        programa = programa or None
        desde, ate = periodo
        fonte = confere_o_pedido(consulta, desde, ate)
        if limite is not None and formato == "json":
            depois = posicao_do_cursor(cursor)
            lidas, total = ou_503(
                lambda: fonte.ranking(programa, desde, ate, depois, limite)
            )
            pagina, cabecalhos = recorta(lidas, depois, limite)
            pagina = com_nomes_do_catalogo(pagina, catalogo)
            corpo = RankingDoTempoDeTela(
                programa=programa, desde=desde, ate=ate, total=total, pessoas=pagina
            )
            return JSONResponse(corpo.model_dump(mode="json"), headers=cabecalhos)
        pessoas = ou_503(lambda: relatorio(fonte.somas(programa, desde, ate)))
        pessoas = com_nomes_do_catalogo(pessoas, catalogo)
        pessoas.sort(key=lambda p: (-p.tempo_de_tela_ms, p.nome, p.pessoa_id))
        if formato == "csv":
            return resposta_em_csv(em_csv(pessoas), "tempo-de-tela.csv")
        poe_o_nome_dos_videos((v for p in pessoas for v in p.por_video), repositorio)
        return RelatorioDeTempoDeTela(
            programa=programa, desde=desde, ate=ate, pessoas=pessoas
        )

    @rotas.get("/tempo-de-tela/videos", response_model=list[VideoDaPessoa])
    def videos_da_pessoa(
        _pessoa: PodeVerORelatorio,
        periodo: Annotated[Periodo, Depends(no_periodo)],
        pessoa_id: Annotated[str, Query(min_length=1, max_length=200)],
        programa: Annotated[str | None, Query(max_length=100)] = None,
        limite: Annotated[int, Query(ge=1, le=LIMITE_DA_PAGINA)] = 25,
        cursor: str | None = None,
    ) -> JSONResponse:
        """Os vídeos de uma pessoa no mesmo filtro do relatório, do maior tempo para o
        menor, uma página por vez (o cursor da próxima em `X-Proximo-Cursor`)."""
        programa = programa or None
        desde, ate = periodo
        fonte = confere_o_pedido(consulta, desde, ate)
        depois = posicao_do_cursor(cursor)
        lidos = ou_503(
            lambda: fonte.videos_da_pessoa(
                pessoa_id, programa, desde, ate, depois, limite
            )
        )
        videos, cabecalhos = recorta(lidos, depois, limite)
        poe_o_nome_dos_videos(videos, repositorio)
        return JSONResponse(
            [v.model_dump(mode="json") for v in videos], headers=cabecalhos
        )

    return rotas
