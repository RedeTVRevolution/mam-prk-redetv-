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
from collections.abc import Callable, Mapping, Sequence
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
)
from api.csv_seguro import csv_em_texto
from api.jobs import RepositorioDeJobs, programas_do_pedido
from api.periodo_padrao import Periodo, agora_em_sao_paulo, dependencia_do_periodo
from api.quem_conta import QuemConta
from api.relatorios import (
    LIMITE_DA_PAGINA,
    PodeVerORelatorio,
    ProgramaDoPedido,
    confere_o_pedido,
    config_e_transporte_do_ambiente,
    consultar_no_bigquery,
    ids_dos_jobs_na_lixeira,
    linhas_da_copia,
    ou_503,
    poe_o_nome_dos_videos,
    posicao_do_cursor,
    recorta,
    resposta_em_csv,
)
from api.texto_como_dado import LinhaDaConsulta

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
        self, programas: Sequence[str], desde: date | None, ate: date | None
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
        self, programas: Sequence[str], desde: date | None, ate: date | None
    ) -> list[MomentoDaPessoa]:
        return [
            MomentoDaPessoa(x.job_id, p.id, p.nome, x.tipo, x.inicio_ms, x.fim_ms)
            for x in linhas_da_copia(
                self._copia, TIPOS_DO_RELATORIO, programas, desde, ate
            )
            for p in x.pessoas
        ]

    def somas(
        self, programas: Sequence[str], desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        return somar(self.momentos(programas, desde, ate))


def ranking_em_python(
    somas: list[PessoaNoVideo],
    depois: int,
    limite: int,
    nomes: Mapping[str, str] | None = None,
) -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
    """O ranking e os totais do período, a partir das somas, na ordem de `relatorio`; a
    página vai de `depois` a `limite + 1` itens (o que passa do limite diz que há mais)."""
    pessoas = relatorio(somas, nomes)
    total = TotalDoTempoDeTela(
        pessoas=len(pessoas),
        tempo_de_tela_ms=sum(p.tempo_de_tela_ms for p in pessoas),
        videos=len({v.job_id for p in pessoas for v in p.por_video if v.aparicoes}),
        aparicoes=sum(p.aparicoes for p in pessoas),
        mencoes_na_fala=sum(p.mencoes_na_fala for p in pessoas),
        mencoes_no_texto=sum(p.mencoes_no_texto for p in pessoas),
    )
    pagina = pessoas[depois : depois + limite + 1]
    return [
        PessoaResumida(**p.model_dump(exclude={"por_video"})) for p in pagina
    ], total


def videos_em_python(
    somas: list[PessoaNoVideo], pessoa_id: str, depois: int, limite: int
) -> "list[VideoDaPessoa]":
    """Os vídeos de uma pessoa, na ordem do relatório, a partir das somas; a página vai
    de `depois` a `limite + 1` itens."""
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

    def somas(
        self, programas: Sequence[str], desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        linhas = consultar_no_bigquery(
            self._config,
            self._transporte,
            colunas=(
                "t.job_id, p.id AS pessoa_id, COALESCE(p.nome, '') AS nome, "
                "t.tipo, t.inicio_ms, t.fim_ms"
            ),
            tipos=TIPOS_DO_RELATORIO,
            programas=programas,
            desde=desde,
            ate=ate,
            unnest_das_pessoas=True,
            condicoes=["p.id IS NOT NULL"],
            depois_da_base=SOMA_EM_SQL,
        )
        return [pessoa_no_video(v) for v in linhas]


class ConsultaComCache:
    """A soma por filtro, calculada uma vez e lembrada (#453): o ranking, a página, a
    pessoa expandida e o CSV saem dela, sem consultar o BigQuery de novo. Só a soma sem
    exclusão fica guardada; a lixeira do catálogo age depois (`SoComQuemConta`)."""

    def __init__(self, consulta: ConsultaDeMomentos, cache: CacheCurto) -> None:
        self._consulta = consulta
        self._cache = cache

    def somas(
        self, programas: Sequence[str], desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        return self._cache.obter(
            ("tempo-de-tela", programas, desde, ate),
            lambda: self._consulta.somas(programas, desde, ate),
        )


class SoComQuemConta:
    """A lixeira do catálogo vale na hora (#591): tira das somas, antes do ranking, dos
    totais, das posições e da paginação, a pessoa que não conta (`QuemConta`), com o
    catálogo lido a cada consulta. A soma de baixo (e seu cache) não muda. O nome de cada
    pessoa que conta é o atual do catálogo, o do destino no fim da cadeia se foi fundida
    (#613), e desempata o ranking antes de cortar a página. O vídeo na lixeira também sai
    (#619): os Jobs dela são lidos uma vez por pedido, depois do cache das somas."""

    def __init__(
        self,
        consulta: ConsultaDeMomentos,
        catalogo: Catalogo,
        jobs: RepositorioDeJobs,
    ) -> None:
        self._consulta = consulta
        self._catalogo = catalogo
        self._jobs = jobs

    def _somas_dos_videos_fora_da_lixeira(
        self, programas: Sequence[str], desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        somas = self._consulta.somas(programas, desde, ate)
        na_lixeira = ids_dos_jobs_na_lixeira(self._jobs)
        return [s for s in somas if s.job_id not in na_lixeira]

    def somas_e_nomes(
        self, programas: Sequence[str], desde: date | None, ate: date | None
    ) -> tuple[list[PessoaNoVideo], dict[str, str]]:
        """As somas de quem conta e o nome atual de cada um, numa leitura do catálogo."""
        somas = self._somas_dos_videos_fora_da_lixeira(programas, desde, ate)
        destinos = QuemConta(self._catalogo).pessoas({s.pessoa_id for s in somas})
        nomes = {i: d.pessoa.nome for i, d in destinos.items() if d.pessoa and d.conta}
        return [s for s in somas if s.pessoa_id in nomes], nomes

    def ranking(
        self,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        depois: int,
        limite: int,
    ) -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
        somas, nomes = self.somas_e_nomes(programas, desde, ate)
        return ranking_em_python(somas, depois, limite, nomes)

    def videos_da_pessoa(
        self,
        pessoa_id: str,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        depois: int,
        limite: int,
    ) -> "list[VideoDaPessoa]":
        if not QuemConta(self._catalogo).contam([pessoa_id]):
            return []
        somas = self._somas_dos_videos_fora_da_lixeira(programas, desde, ate)
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

    programas: list[str]
    desde: date | None
    ate: date | None
    total: TotalDoTempoDeTela
    pessoas: list[PessoaResumida]


class RelatorioDeTempoDeTela(BaseModel):
    programas: list[str]
    desde: date | None
    ate: date | None
    pessoas: list[PessoaNoRelatorio]


def relatorio(
    somas: list[PessoaNoVideo], nomes: Mapping[str, str] | None = None
) -> list[PessoaNoRelatorio]:
    """Uma linha por pessoa, do maior tempo de tela para o menor e, no empate, pelo nome
    e pelo id.

    A pessoa é o id do catálogo. O nome vem de `nomes` (o atual do catálogo, #417 e #613,
    que tem de trazer toda pessoa das somas); sem o mapa, é o que mais aparece nas linhas
    dela (um vídeo copiado antes de uma correção de grafia não parte a pessoa em duas).
    """
    por_pessoa: dict[str, list[PessoaNoVideo]] = defaultdict(list)
    for s in somas:
        por_pessoa[s.pessoa_id].append(s)
    pessoas: list[PessoaNoRelatorio] = []
    for pessoa_id, dela in por_pessoa.items():
        contagem: Counter[str] = Counter()
        for s in dela:
            contagem.update(s.nomes)
        nome = (
            nomes[pessoa_id]
            if nomes is not None
            else min(contagem, key=lambda n: (-contagem[n], n))
        )
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
    consulta: ConsultaDeMomentos | None,
    repositorio: RepositorioDeJobs,
    catalogo: Catalogo,
    relogio: Callable[[], datetime] = agora_em_sao_paulo,
) -> APIRouter:
    rotas = APIRouter(prefix="/relatorios")
    no_periodo = dependencia_do_periodo(relogio)
    com_lixeira = (
        SoComQuemConta(consulta, catalogo, repositorio)
        if consulta is not None
        else None
    )

    @rotas.get(
        "/tempo-de-tela",
        response_model=RelatorioDeTempoDeTela | RankingDoTempoDeTela,
    )
    def tempo_de_tela(
        _pessoa: PodeVerORelatorio,
        periodo: Annotated[Periodo, Depends(no_periodo)],
        programa: Annotated[list[ProgramaDoPedido] | None, Query()] = None,
        formato: Literal["json", "csv"] = "json",
        limite: Annotated[int | None, Query(ge=1, le=LIMITE_DA_PAGINA)] = None,
        cursor: Annotated[str | None, LinhaDaConsulta(500)] = None,
    ) -> Any:
        """`desde` e `ate` são datas de exibição, as duas inclusive; sem `programa` (ou só vazios), todos; `programa` se repete, um por programa marcado. Com `limite`, uma página do ranking (sem os
        vídeos, com os totais do período) e o cursor da próxima em `X-Proximo-Cursor`;
        os vídeos de uma pessoa ficam em `/tempo-de-tela/videos`. O CSV vem sempre
        inteiro."""
        programas = programas_do_pedido(programa)
        desde, ate = periodo
        fonte = confere_o_pedido(com_lixeira, desde, ate)
        if limite is not None and formato == "json":
            depois = posicao_do_cursor(cursor)
            lidas, total = ou_503(
                lambda: fonte.ranking(programas, desde, ate, depois, limite)
            )
            pagina, cabecalhos = recorta(lidas, depois, limite)
            corpo = RankingDoTempoDeTela(
                programas=list(programas),
                desde=desde,
                ate=ate,
                total=total,
                pessoas=pagina,
            )
            return JSONResponse(corpo.model_dump(mode="json"), headers=cabecalhos)
        pessoas = ou_503(lambda: relatorio(*fonte.somas_e_nomes(programas, desde, ate)))
        if formato == "csv":
            return resposta_em_csv(em_csv(pessoas), "tempo-de-tela.csv")
        poe_o_nome_dos_videos((v for p in pessoas for v in p.por_video), repositorio)
        return RelatorioDeTempoDeTela(
            programas=list(programas), desde=desde, ate=ate, pessoas=pessoas
        )

    @rotas.get("/tempo-de-tela/videos", response_model=list[VideoDaPessoa])
    def videos_da_pessoa(
        _pessoa: PodeVerORelatorio,
        periodo: Annotated[Periodo, Depends(no_periodo)],
        pessoa_id: Annotated[str, LinhaDaConsulta(200, min_length=1)],
        programa: Annotated[list[ProgramaDoPedido] | None, Query()] = None,
        limite: Annotated[int, Query(ge=1, le=LIMITE_DA_PAGINA)] = 25,
        cursor: Annotated[str | None, LinhaDaConsulta(500)] = None,
    ) -> JSONResponse:
        """Os vídeos de uma pessoa no mesmo filtro do relatório, do maior tempo para o
        menor, uma página por vez (o cursor da próxima em `X-Proximo-Cursor`)."""
        programas = programas_do_pedido(programa)
        desde, ate = periodo
        fonte = confere_o_pedido(com_lixeira, desde, ate)
        depois = posicao_do_cursor(cursor)
        lidos = ou_503(
            lambda: fonte.videos_da_pessoa(
                pessoa_id, programas, desde, ate, depois, limite
            )
        )
        videos, cabecalhos = recorta(lidos, depois, limite)
        poe_o_nome_dos_videos(videos, repositorio)
        return JSONResponse(
            [v.model_dump(mode="json") for v in videos], headers=cabecalhos
        )

    return rotas
