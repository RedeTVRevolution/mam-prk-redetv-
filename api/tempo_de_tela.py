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

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Annotated, Any, Literal, NamedTuple, Protocol

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
    parametro_de_lista,
)
from api.csv_seguro import csv_em_texto
from api.fuso import agora_em_sao_paulo
from api.jobs import programas_do_pedido
from api.modelo_do_job import RepositorioDeJobs
from api.periodo_padrao import Periodo, dependencia_do_periodo
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
    tipo: str
    inicio_ms: int
    fim_ms: int


@dataclass(frozen=True)
class PessoaNoVideo:
    """A soma de uma pessoa num vídeo: o que o SQL devolve, uma linha por par."""

    job_id: str
    pessoa_id: str
    tempo_de_tela_ms: int
    aparicoes: int  # depois de unir as sobrepostas
    mencoes_na_fala: int
    mencoes_no_texto: int


class ConsultaDeMomentos(Protocol):
    def somas(
        self, programas: Sequence[str], desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        """Uma soma por pessoa e vídeo; `desde` e `ate` são datas de exibição, inclusive."""

    def aparicoes_unidas(
        self,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        pessoas: Sequence[str],
    ) -> list[tuple[str, str, int, int]]:
        """Os intervalos de aparição já unidos por vídeo e pessoa (`job_id`, `pessoa_id`,
        `inicio_ms`, `fim_ms`), só das `pessoas` pedidas, no mesmo filtro das somas (#784)."""


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
            MomentoDaPessoa(x.job_id, p.id, x.tipo, x.inicio_ms, x.fim_ms)
            for x in linhas_da_copia(
                self._copia, TIPOS_DO_RELATORIO, programas, desde, ate
            )
            for p in x.pessoas
        ]

    def somas(
        self, programas: Sequence[str], desde: date | None, ate: date | None
    ) -> list[PessoaNoVideo]:
        return somar(self.momentos(programas, desde, ate))

    def aparicoes_unidas(
        self,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        pessoas: Sequence[str],
    ) -> list[tuple[str, str, int, int]]:
        por_par: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
        for m in self.momentos(programas, desde, ate):
            if m.tipo == "aparicao" and m.pessoa_id in pessoas:
                por_par[(m.job_id, m.pessoa_id)].append((m.inicio_ms, m.fim_ms))
        return [(j, p, i, f) for (j, p), v in por_par.items() for i, f in _uniao(v)]


def ranking_em_python(
    somas: list[PessoaNoVideo],
    depois: int,
    limite: int,
    nomes: Mapping[str, str],
) -> "tuple[list[PessoaResumida], TotalDoTempoDeTela]":
    """O ranking e os totais do período, a partir das somas, na ordem de `relatorio`; a
    página vai de `depois` a `limite + 1` itens (o que passa do limite diz que há mais)."""
    pessoas = _linhas(somas, nomes)
    total = TotalDoTempoDeTela(
        pessoas=len(pessoas),
        tempo_de_tela_ms=sum(p.tempo_de_tela_ms for p in pessoas),
        videos=len({s.job_id for s in somas if s.aparicoes}),
        aparicoes=sum(p.aparicoes for p in pessoas),
        mencoes_na_fala=sum(p.mencoes_na_fala for p in pessoas),
        mencoes_no_texto=sum(p.mencoes_no_texto for p in pessoas),
    )
    pagina = pessoas[depois : depois + limite + 1]
    return [PessoaResumida(**p._asdict()) for p in pagina], total


def videos_em_python(
    somas: list[PessoaNoVideo], pessoa_id: str, depois: int, limite: int
) -> "list[VideoDaPessoa]":
    """Os vídeos de uma pessoa, na ordem do relatório, a partir das somas; a página vai
    de `depois` a `limite + 1` itens."""
    dela = [s for s in somas if s.pessoa_id == pessoa_id]
    # o nome não entra nos vídeos: o mapa só satisfaz `relatorio`
    por_video = relatorio(dela, {pessoa_id: ""})[0].por_video if dela else []
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

# O que vem depois de `WITH base AS (...)`: uma linha por pessoa e vídeo, com o tempo
# das aparições unidas e as contagens de menções. As contagens saem de uma passada só
# pela `base` (cada CTE que a lê é mais uma leitura da tabela).
_CTES_DA_SOMA = f""", {UNIAO_EM_SQL},
tempo AS (
  SELECT job_id, pessoa_id, SUM(fim_ms - inicio_ms) AS tempo_ms, COUNT(*) AS aparicoes
  FROM unidas
  GROUP BY job_id, pessoa_id
),
contagens AS (
  SELECT job_id, pessoa_id,
    SUM(CASE WHEN tipo = 'mencao_na_fala' THEN 1 ELSE 0 END) AS na_fala,
    SUM(CASE WHEN tipo = 'mencao_no_texto' THEN 1 ELSE 0 END) AS no_texto
  FROM base
  GROUP BY job_id, pessoa_id
)"""
_SELECT_POR_VIDEO = """SELECT c.job_id, c.pessoa_id, IFNULL(t.tempo_ms, 0) AS tempo_ms,
  IFNULL(t.aparicoes, 0) AS aparicoes, c.na_fala, c.no_texto
FROM contagens AS c
LEFT JOIN tempo AS t ON t.job_id = c.job_id AND t.pessoa_id = c.pessoa_id"""
SOMA_EM_SQL = f"{_CTES_DA_SOMA}\n{_SELECT_POR_VIDEO}"


def pessoa_no_video(v: Sequence[Any]) -> PessoaNoVideo:
    """Uma linha do `SOMA_EM_SQL`, na ordem das colunas do SELECT final."""
    return PessoaNoVideo(
        job_id=v[0],
        pessoa_id=v[1],
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
            colunas=("t.job_id, p.id AS pessoa_id, t.tipo, t.inicio_ms, t.fim_ms"),
            tipos=TIPOS_DO_RELATORIO,
            programas=programas,
            desde=desde,
            ate=ate,
            unnest_das_pessoas=True,
            condicoes=["p.id IS NOT NULL"],
            depois_da_base=SOMA_EM_SQL,
        )
        return [pessoa_no_video(v) for v in linhas]

    def aparicoes_unidas(
        self,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        pessoas: Sequence[str],
    ) -> list[tuple[str, str, int, int]]:
        linhas = consultar_no_bigquery(
            self._config,
            self._transporte,
            colunas=("t.job_id, p.id AS pessoa_id, t.tipo, t.inicio_ms, t.fim_ms"),
            tipos=TIPOS_DO_RELATORIO,
            programas=programas,
            desde=desde,
            ate=ate,
            unnest_das_pessoas=True,
            condicoes=["p.id IN UNNEST(@pessoas)"],
            parametros=[parametro_de_lista("pessoas", pessoas)],
            depois_da_base=f", {UNIAO_EM_SQL}\n"
            "SELECT job_id, pessoa_id, inicio_ms, fim_ms FROM unidas",
        )
        return [(v[0], v[1], int(v[2]), int(v[3])) for v in linhas]


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

    def aparicoes_unidas(
        self,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        pessoas: Sequence[str],
    ) -> list[tuple[str, str, int, int]]:
        """Só repassa: as pessoas pedidas mudam com o catálogo, não há o que guardar."""
        return self._consulta.aparicoes_unidas(programas, desde, ate, pessoas)


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
        return self._no_destino(somas, programas, desde, ate)

    def _no_destino(
        self,
        somas: list[PessoaNoVideo],
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        so_o_destino: str | None = None,
    ) -> tuple[list[PessoaNoVideo], dict[str, str]]:
        """Passa cada soma ao destino da cadeia de fusão (#784) e tira quem não conta. Num
        vídeo com duas ou mais pessoas do mesmo destino a soma de baixo já unida não se
        reúne em Python: os intervalos vêm da consulta, só dessas pessoas. Com `so_o_destino`,
        só os pares desse destino entram (os vídeos de uma pessoa não pagam a fusão alheia)."""
        destinos = QuemConta(self._catalogo).pessoas({s.pessoa_id for s in somas})
        alvo = {i: d.pessoa.id for i, d in destinos.items() if d.pessoa and d.conta}
        nomes = {
            d.pessoa.id: d.pessoa.nome
            for d in destinos.values()
            if d.pessoa and d.conta
        }
        por_par: dict[tuple[str, str], list[PessoaNoVideo]] = defaultdict(list)
        for s in somas:
            if s.pessoa_id in alvo and so_o_destino in (None, alvo[s.pessoa_id]):
                por_par[(s.job_id, alvo[s.pessoa_id])].append(s)
        juntas = {k: v for k, v in por_par.items() if len(v) > 1}
        intervalos: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
        if juntas:
            pessoas = sorted({s.pessoa_id for v in juntas.values() for s in v})
            for job_id, pessoa_id, inicio, fim in self._consulta.aparicoes_unidas(
                programas, desde, ate, pessoas
            ):
                intervalos[(job_id, pessoa_id)].append((inicio, fim))
        return [_no_destino(k, v, intervalos) for k, v in por_par.items()], nomes

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
        somas = self._somas_dos_videos_fora_da_lixeira(programas, desde, ate)
        no_destino, _ = self._no_destino(somas, programas, desde, ate, pessoa_id)
        return videos_em_python(no_destino, pessoa_id, depois, limite)


def _no_destino(
    chave: tuple[str, str],
    somas: list[PessoaNoVideo],
    intervalos: Mapping[tuple[str, str], list[tuple[int, int]]],
) -> PessoaNoVideo:
    """A soma do destino (`chave`: vídeo e destino) a partir das de suas pessoas no vídeo."""
    job_id, destino = chave
    if len(somas) == 1:
        return replace(somas[0], pessoa_id=destino)
    unidos = _uniao([i for s in somas for i in intervalos[(job_id, s.pessoa_id)]])
    return PessoaNoVideo(
        job_id=job_id,
        pessoa_id=destino,
        tempo_de_tela_ms=sum(fim - ini for ini, fim in unidos),
        aparicoes=len(unidos),
        mencoes_na_fala=sum(s.mencoes_na_fala for s in somas),
        mencoes_no_texto=sum(s.mencoes_no_texto for s in somas),
    )


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


class _Linha(NamedTuple):
    """Uma pessoa no ranking, sem os vídeos: o que o ranking, os totais e o CSV usam."""

    pessoa_id: str
    nome: str
    tempo_de_tela_ms: int
    videos: int
    aparicoes: int
    mencoes_na_fala: int
    mencoes_no_texto: int


def _linhas(somas: list[PessoaNoVideo], nomes: Mapping[str, str]) -> list[_Linha]:
    """Uma linha por pessoa, do maior tempo de tela para o menor e, no empate, pelo nome
    e pelo id. Só tuplas e números: sem um objeto por par pessoa e vídeo.

    A pessoa é o id do catálogo. O nome vem de `nomes` (o atual do catálogo, #417 e #613,
    que tem de trazer toda pessoa das somas).
    """
    # por pessoa: tempo, vídeos com aparição, aparições, menções na fala e no texto
    somados: dict[str, list[int]] = {}
    for s in somas:
        c = somados.get(s.pessoa_id)
        if c is None:
            c = somados[s.pessoa_id] = [0, 0, 0, 0, 0]
        c[0] += s.tempo_de_tela_ms
        c[1] += s.aparicoes > 0
        c[2] += s.aparicoes
        c[3] += s.mencoes_na_fala
        c[4] += s.mencoes_no_texto
    linhas = [
        _Linha(pessoa_id, nomes[pessoa_id], *c) for pessoa_id, c in somados.items()
    ]
    linhas.sort(key=lambda p: (-p.tempo_de_tela_ms, p.nome, p.pessoa_id))
    return linhas


def relatorio(
    somas: list[PessoaNoVideo], nomes: Mapping[str, str]
) -> list[PessoaNoRelatorio]:
    """O ranking de `_linhas`, cada pessoa com seus vídeos (do maior tempo para o menor);
    os objetos por vídeo só nascem aqui, no JSON completo e nos vídeos de uma pessoa."""
    por_pessoa: dict[str, list[VideoDaPessoa]] = defaultdict(list)
    for s in somas:
        por_pessoa[s.pessoa_id].append(
            VideoDaPessoa(
                job_id=s.job_id,
                tempo_de_tela_ms=s.tempo_de_tela_ms,
                aparicoes=s.aparicoes,
                mencoes_na_fala=s.mencoes_na_fala,
                mencoes_no_texto=s.mencoes_no_texto,
            )
        )
    for videos in por_pessoa.values():
        videos.sort(key=lambda v: (-v.tempo_de_tela_ms, v.job_id))
    return [
        PessoaNoRelatorio(**linha._asdict(), por_video=por_pessoa[linha.pessoa_id])
        for linha in _linhas(somas, nomes)
    ]


def em_csv(pessoas: Sequence[PessoaResumida | _Linha]) -> str:
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
        somas_e_nomes = ou_503(lambda: fonte.somas_e_nomes(programas, desde, ate))
        if formato == "csv":
            return resposta_em_csv(em_csv(_linhas(*somas_e_nomes)), "tempo-de-tela.csv")
        pessoas = relatorio(*somas_e_nomes)
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
