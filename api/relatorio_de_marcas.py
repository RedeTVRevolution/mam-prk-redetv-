"""Relatório por marca e por tipo de inserção (#267): `GET /v1/relatorios/marcas`.

Lê da cópia no BigQuery (#260) as linhas `comercial`, uma por inserção. Por marca, soma o
número de inserções, o tempo (a soma das durações, sem unir sobreposições: uma marca
incidental durante o merchan conta nas duas) e o número de vídeos; o detalhe por tipo de
inserção e a lista das inserções, com o vídeo e o tempo, vêm junto. A base (permissão,
filtros, CSV, erros) é a de `api.relatorios`, a mesma do tempo de tela. A soma é feita no
BigQuery (#363): ele devolve uma linha por marca, tipo de inserção e vídeo, com os
intervalos das inserções; o Python só monta a resposta.
"""

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal, Protocol, get_args

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.cache_curto import CacheCurto
from api.comparador import normalizar
from api.copia_bigquery import ConfigDoBigQuery, CopiaEmMemoria, Transporte, parametro
from api.csv_seguro import csv_em_texto
from api.decupagem import Comercial
from api.erros import lido
from api.jobs import RepositorioDeJobs
from api.lixeira_na_leitura import (
    PurgasDeMarca,
    conta_depois_do_corte,
    cortes_validos,
    nomes_de_marca_na_lixeira,
)
from api.marcas import CatalogoDeMarcas
from api.periodo_padrao import Periodo, agora_em_sao_paulo, dependencia_do_periodo
from api.relatorios import (
    LIMITE_DA_PAGINA,
    PodeVerORelatorio,
    confere_o_pedido,
    config_e_transporte_do_ambiente,
    consultar_no_bigquery,
    linhas_da_copia,
    ou_503,
    poe_o_nome_dos_videos,
    posicao_do_cursor,
    recorta,
    resposta_em_csv,
)
from api.texto_como_dado import LinhaDaConsulta

TIPOS_DE_INSERCAO: tuple[str, ...] = get_args(Comercial.model_fields["tipo"].annotation)
COLUNAS_DO_CSV = ("marca", "tipo", "insercoes", "tempo_ms", "videos")
TIPO_DO_TOTAL = "todos"  # no CSV, a linha com o total da marca


@dataclass(frozen=True)
class Insercao:
    job_id: str
    marca: str
    tipo: str
    inicio_ms: int
    fim_ms: int


@dataclass(frozen=True)
class InsercoesDaMarca:
    """A soma de uma marca, num tipo de inserção, num vídeo: o que o SQL devolve."""

    marca: str
    tipo: str
    job_id: str
    insercoes: int
    tempo_ms: int
    intervalos: list[tuple[int, int]]  # início e fim de cada inserção


class ConsultaDeInsercoes(Protocol):
    def somas(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
    ) -> list[InsercoesDaMarca]:
        """As inserções com marca, somadas; `desde` e `ate` são datas de exibição,
        inclusive."""


def somar(insercoes: list[Insercao]) -> list[InsercoesDaMarca]:
    """A soma em Python do que `SOMA_EM_SQL` faz no BigQuery (o dublê e a referência)."""
    grupos: dict[tuple[str, str, str], list[Insercao]] = defaultdict(list)
    for i in insercoes:
        grupos[(i.marca, i.tipo, i.job_id)].append(i)
    return [
        InsercoesDaMarca(
            marca=marca,
            tipo=tipo,
            job_id=job_id,
            insercoes=len(dele),
            tempo_ms=sum(i.fim_ms - i.inicio_ms for i in dele),
            intervalos=sorted((i.inicio_ms, i.fim_ms) for i in dele),
        )
        for (marca, tipo, job_id), dele in grupos.items()
    ]


class ConsultaEmMemoria:
    """Dublê da consulta: os mesmos filtros e a mesma soma sobre a cópia em memória."""

    def __init__(self, copia: CopiaEmMemoria) -> None:
        self._copia = copia

    def insercoes(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
    ) -> list[Insercao]:
        achadas: list[Insercao] = []
        for x in linhas_da_copia(self._copia, ("comercial",), programa, desde, ate):
            if x.marca and x.tipo_de_insercao and tipo in (None, x.tipo_de_insercao):
                achadas.append(
                    Insercao(
                        x.job_id, x.marca, x.tipo_de_insercao, x.inicio_ms, x.fim_ms
                    )
                )
        return achadas

    def somas(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
    ) -> list[InsercoesDaMarca]:
        return somar(self.insercoes(programa, desde, ate, tipo))


def ranking_em_python(
    somas: list[InsercoesDaMarca], depois: int, limite: int
) -> "tuple[list[MarcaResumida], TotalDasMarcas]":
    """O ranking e os totais do período, a partir das somas; a página vai de `depois`
    a `limite + 1` itens (o que passa do limite diz que há mais)."""
    marcas = relatorio(somas)
    total = TotalDasMarcas(
        marcas=len(marcas),
        insercoes=sum(m.insercoes for m in marcas),
        tempo_ms=sum(m.tempo_ms for m in marcas),
        videos=len({i.job_id for m in marcas for i in m.lista}),
    )
    pagina = marcas[depois : depois + limite + 1]
    return [MarcaResumida(**m.model_dump(exclude={"lista"})) for m in pagina], total


def lista_em_python(
    somas: list[InsercoesDaMarca], marca: str, depois: int, limite: int
) -> "list[InsercaoNoRelatorio]":
    """As inserções de uma marca, na ordem do relatório, a partir das somas; a página vai
    de `depois` a `limite + 1` itens."""
    dela = [s for s in somas if s.marca == marca]
    lista = relatorio(dela)[0].lista if dela else []
    return lista[depois : depois + limite + 1]


# Os intervalos das inserções, num texto JSON. É o único trecho só do BigQuery: o teste
# troca por `json_group_array` e roda o resto num SQLite.
INTERVALOS_EM_JSON = (
    "TO_JSON_STRING(ARRAY_AGG(STRUCT(inicio_ms, fim_ms) ORDER BY inicio_ms, fim_ms))"
)

# O que vem depois de `WITH base AS (...)`: uma linha por marca, tipo e vídeo. Os
# intervalos vêm junto porque a resposta lista as inserções, então o tamanho do resultado
# ainda cresce com o número delas; o teto que resta é a memória da instância (o resultado
# vem em quantas páginas precisar).
SOMA_EM_SQL = f"""SELECT marca, tipo, job_id, COUNT(*), SUM(fim_ms - inicio_ms),
  {INTERVALOS_EM_JSON}
FROM base
GROUP BY marca, tipo, job_id"""


def insercoes_da_marca(v: Sequence[Any]) -> InsercoesDaMarca:
    """Uma linha do `SOMA_EM_SQL`, na ordem das colunas do SELECT."""
    return InsercoesDaMarca(
        marca=v[0],
        tipo=v[1],
        job_id=v[2],
        insercoes=int(v[3]),
        tempo_ms=int(v[4]),
        intervalos=sorted(
            (int(i["inicio_ms"]), int(i["fim_ms"])) for i in json.loads(v[5])
        ),
    )


class ConsultaBigQuery:
    """A consulta real: REST com o mesmo transporte da cópia."""

    def __init__(self, config: ConfigDoBigQuery, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def somas(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
    ) -> list[InsercoesDaMarca]:
        # Marca ou tipo vazio também fica de fora, como no dublê.
        condicoes = [
            "NULLIF(t.marca, '') IS NOT NULL",
            "NULLIF(t.tipo_de_insercao, '') IS NOT NULL",
        ]
        parametros = []
        if tipo is not None:
            condicoes.append("t.tipo_de_insercao = @tipo_de_insercao")
            parametros.append(parametro("tipo_de_insercao", tipo))
        linhas = consultar_no_bigquery(
            self._config,
            self._transporte,
            colunas=(
                "t.job_id, t.marca, t.tipo_de_insercao AS tipo, t.inicio_ms, t.fim_ms"
            ),
            tipos=("comercial",),
            programa=programa,
            desde=desde,
            ate=ate,
            condicoes=condicoes,
            parametros=parametros,
            depois_da_base=SOMA_EM_SQL,
        )
        return [insercoes_da_marca(v) for v in linhas]


class ConsultaComCache:
    """A soma por filtro, calculada uma vez e lembrada (#453): o ranking, a página, a lista
    de uma marca e o CSV saem dela, sem consultar o BigQuery de novo. Só a soma sem exclusão
    fica guardada; a lixeira do catálogo age depois (`SoMarcasQueContam`)."""

    def __init__(self, consulta: ConsultaDeInsercoes, cache: CacheCurto) -> None:
        self._consulta = consulta
        self._cache = cache

    def somas(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
    ) -> list[InsercoesDaMarca]:
        return self._cache.obter(
            ("marcas", programa, desde, ate, tipo),
            lambda: self._consulta.somas(programa, desde, ate, tipo),
        )

    def ranking(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
        depois: int,
        limite: int,
    ) -> "tuple[list[MarcaResumida], TotalDasMarcas]":
        # O ranking não é guardado pronto: sai das somas, onde a exclusão já agiu.
        return ranking_em_python(self.somas(programa, desde, ate, tipo), depois, limite)

    def lista_da_marca(
        self,
        marca: str,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
        depois: int,
        limite: int,
    ) -> "list[InsercaoNoRelatorio]":
        somas = self.somas(programa, desde, ate, tipo)
        return lista_em_python(somas, marca, depois, limite)


class SoMarcasQueContam:
    """A lixeira do catálogo vale na hora (#593): tira das somas, antes do ranking, dos
    totais, das posições e da paginação, o texto que bate com o nome ou apelido de uma marca
    na lixeira, com o catálogo lido a cada consulta. A soma de baixo (e seu cache) não muda.

    A marca purgada (#595) deixa um registro: as ocorrências do nome em vídeos de Jobs
    criados até o instante da purga ficam fora, as dos criados depois contam. A data vem de
    `Job.criado_em` no Firestore (não muda com o reprocessamento nem com a recópia), lida em
    lote, uma vez por vídeo, só para as somas que batem com um registro; Job ausente conta
    como anterior; falha de leitura é erro (503), não "Job ausente"."""

    def __init__(
        self,
        consulta: ConsultaDeInsercoes,
        marcas: CatalogoDeMarcas,
        purgas: PurgasDeMarca,
        jobs: RepositorioDeJobs,
    ) -> None:
        self._consulta = consulta
        self._marcas = marcas
        self._purgas = purgas
        self._jobs = jobs

    def _cortes(self, nomes: set[str]) -> dict[str, datetime]:
        return cortes_validos(lido(self._purgas.todas), self._marcas, nomes)

    def somas(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
    ) -> list[InsercoesDaMarca]:
        somas = self._consulta.somas(programa, desde, ate, tipo)
        fora = nomes_de_marca_na_lixeira(self._marcas)
        return self._depois_do_corte(
            [s for s in somas if normalizar(s.marca) not in fora]
        )

    def insercoes_dos_nomes(self, nomes: set[str]) -> int:
        """Quantas inserções de todo o histórico, com o texto em `nomes` (normalizados),
        o relatório contaria se a marca não estivesse na lixeira (#597): as somas sem a
        exclusão da lixeira, só com o corte das purgas. Cada inserção é uma linha da cópia,
        com ou sem vínculo no catálogo, então conta uma vez."""
        somas = self._consulta.somas(None, None, None, None)
        return sum(
            s.insercoes
            for s in self._depois_do_corte(
                [s for s in somas if normalizar(s.marca) in nomes]
            )
        )

    def _depois_do_corte(self, somas: list[InsercoesDaMarca]) -> list[InsercoesDaMarca]:
        # `normalizar` uma vez por marca distinta, não por linha de soma.
        nome = {m: normalizar(m) for m in {s.marca for s in somas}}
        cortes = self._cortes(set(nome.values()))
        cortadas = [s for s in somas if nome[s.marca] in cortes]
        if not cortadas:
            return somas
        criados = {
            j.id: j.criado_em
            for j in lido(lambda: self._jobs.obter_varios({s.job_id for s in cortadas}))
        }
        return [
            s
            for s in somas
            if (corte := cortes.get(nome[s.marca])) is None
            or conta_depois_do_corte(criados.get(s.job_id), corte)
        ]

    def ranking(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
        depois: int,
        limite: int,
    ) -> "tuple[list[MarcaResumida], TotalDasMarcas]":
        return ranking_em_python(self.somas(programa, desde, ate, tipo), depois, limite)

    def lista_da_marca(
        self,
        marca: str,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
        depois: int,
        limite: int,
    ) -> "list[InsercaoNoRelatorio]":
        somas = self.somas(programa, desde, ate, tipo)
        return lista_em_python(somas, marca, depois, limite)


def consulta_do_ambiente(ambiente: Any) -> ConsultaBigQuery | None:
    """A consulta configurada, ou `None` se o ambiente não diz onde a cópia mora."""
    onde = config_e_transporte_do_ambiente(ambiente)
    return ConsultaBigQuery(*onde) if onde else None


class InsercaoNoRelatorio(BaseModel):
    job_id: str
    nome: str | None = None
    tipo: str
    inicio_ms: int
    fim_ms: int


class TotalPorTipo(BaseModel):
    tipo: str
    insercoes: int
    tempo_ms: int
    videos: int


class MarcaResumida(BaseModel):
    marca: str
    insercoes: int
    tempo_ms: int
    videos: int
    por_tipo: list[TotalPorTipo]


class MarcaNoRelatorio(MarcaResumida):
    lista: list[InsercaoNoRelatorio]


class TotalDasMarcas(BaseModel):
    """O período inteiro, não só a página: os números dos cartões."""

    marcas: int
    insercoes: int
    tempo_ms: int
    videos: int


class RankingDeMarcas(BaseModel):
    """O relatório com `limite`: uma página das marcas, sem a lista das inserções."""

    programa: str | None
    desde: date | None
    ate: date | None
    tipo: str | None
    total: TotalDasMarcas
    marcas: list[MarcaResumida]


class RelatorioDeMarcas(BaseModel):
    programa: str | None
    desde: date | None
    ate: date | None
    tipo: str | None
    marcas: list[MarcaNoRelatorio]


def _total(tipo: str, grupos: list[InsercoesDaMarca]) -> TotalPorTipo:
    return TotalPorTipo(
        tipo=tipo,
        insercoes=sum(g.insercoes for g in grupos),
        tempo_ms=sum(g.tempo_ms for g in grupos),
        videos=len({g.job_id for g in grupos}),
    )


def _ordem_dos_tipos(tipos: set[str]) -> list[str]:
    return [t for t in TIPOS_DE_INSERCAO if t in tipos] + sorted(
        tipos - set(TIPOS_DE_INSERCAO)
    )


def relatorio(somas: list[InsercoesDaMarca]) -> list[MarcaNoRelatorio]:
    """Uma linha por marca, do maior tempo para o menor; o detalhe por tipo segue a ordem
    de `TIPOS_DE_INSERCAO` (um tipo que a decupagem não tem mais, de uma linha antiga, vem
    no fim, para as partes fecharem com o total) e a lista das inserções, a do vídeo e do
    tempo (no empate, a do tipo)."""
    por_marca: dict[str, list[InsercoesDaMarca]] = defaultdict(list)
    for g in somas:
        por_marca[g.marca].append(g)
    marcas: list[MarcaNoRelatorio] = []
    for marca, dela in por_marca.items():
        total = _total(TIPO_DO_TOTAL, dela)
        ordem = _ordem_dos_tipos({g.tipo for g in dela})
        lista = [
            InsercaoNoRelatorio(job_id=g.job_id, tipo=g.tipo, inicio_ms=ini, fim_ms=fim)
            for g in dela
            for ini, fim in g.intervalos
        ]
        lista.sort(key=lambda i: (i.job_id, i.inicio_ms, i.fim_ms, i.tipo))
        marcas.append(
            MarcaNoRelatorio(
                marca=marca,
                insercoes=total.insercoes,
                tempo_ms=total.tempo_ms,
                videos=total.videos,
                por_tipo=[_total(t, [g for g in dela if g.tipo == t]) for t in ordem],
                lista=lista,
            )
        )
    marcas.sort(key=lambda m: (-m.tempo_ms, m.marca))
    return marcas


def em_csv(marcas: list[MarcaNoRelatorio]) -> str:
    """Por marca, uma linha de total (`tipo` = `todos`) e uma por tipo de inserção."""
    linhas: list[list[object]] = []
    for m in marcas:
        linhas.append([m.marca, TIPO_DO_TOTAL, m.insercoes, m.tempo_ms, m.videos])
        linhas += [
            [m.marca, t.tipo, t.insercoes, t.tempo_ms, t.videos] for t in m.por_tipo
        ]
    return csv_em_texto(COLUNAS_DO_CSV, linhas)


def criar_rotas_das_marcas(
    consulta: ConsultaDeInsercoes | None,
    repositorio: RepositorioDeJobs,
    catalogo: CatalogoDeMarcas,
    purgas: PurgasDeMarca,
    relogio: Callable[[], datetime] = agora_em_sao_paulo,
) -> APIRouter:
    rotas = APIRouter(prefix="/relatorios")
    no_periodo = dependencia_do_periodo(relogio)
    com_lixeira = (
        SoMarcasQueContam(consulta, catalogo, purgas, repositorio)
        if consulta is not None
        else None
    )

    def _confere(
        programa: str | None, desde: date | None, ate: date | None, tipo: str | None
    ) -> SoMarcasQueContam:
        if tipo is not None and tipo not in TIPOS_DE_INSERCAO:
            raise HTTPException(422, f"Tipo de inserção desconhecido: {tipo}")
        return confere_o_pedido(com_lixeira, desde, ate)

    @rotas.get("/marcas", response_model=RelatorioDeMarcas | RankingDeMarcas)
    def marcas(
        _pessoa: PodeVerORelatorio,
        periodo: Annotated[Periodo, Depends(no_periodo)],
        programa: Annotated[str | None, LinhaDaConsulta(100)] = None,
        tipo: Annotated[str | None, LinhaDaConsulta(40)] = None,
        formato: Literal["json", "csv"] = "json",
        limite: Annotated[int | None, Query(ge=1, le=LIMITE_DA_PAGINA)] = None,
        cursor: Annotated[str | None, LinhaDaConsulta(500)] = None,
    ) -> Any:
        """`desde` e `ate` são datas de exibição, as duas inclusive; sem programa (ou com
        `programa=` vazio) e sem tipo (ou vazio), todos. Com `limite`, uma página do
        ranking (sem a lista das inserções, com os totais do período) e o cursor da
        próxima em `X-Proximo-Cursor`; as inserções de uma marca ficam em
        `/marcas/insercoes`. O CSV vem sempre inteiro."""
        programa = programa or None
        tipo = tipo or None
        desde, ate = periodo
        fonte = _confere(programa, desde, ate, tipo)
        if limite is not None and formato == "json":
            depois = posicao_do_cursor(cursor)
            lidas, total = ou_503(
                lambda: fonte.ranking(programa, desde, ate, tipo, depois, limite)
            )
            pagina, cabecalhos = recorta(lidas, depois, limite)
            corpo = RankingDeMarcas(
                programa=programa,
                desde=desde,
                ate=ate,
                tipo=tipo,
                total=total,
                marcas=pagina,
            )
            return JSONResponse(corpo.model_dump(mode="json"), headers=cabecalhos)
        achadas = ou_503(lambda: relatorio(fonte.somas(programa, desde, ate, tipo)))
        if formato == "csv":
            return resposta_em_csv(em_csv(achadas), "marcas.csv")
        poe_o_nome_dos_videos((i for m in achadas for i in m.lista), repositorio)
        return RelatorioDeMarcas(
            programa=programa, desde=desde, ate=ate, tipo=tipo, marcas=achadas
        )

    @rotas.get("/marcas/insercoes", response_model=list[InsercaoNoRelatorio])
    def lista_da_marca(
        _pessoa: PodeVerORelatorio,
        periodo: Annotated[Periodo, Depends(no_periodo)],
        marca: Annotated[str, LinhaDaConsulta(200, min_length=1)],
        programa: Annotated[str | None, LinhaDaConsulta(100)] = None,
        tipo: Annotated[str | None, LinhaDaConsulta(40)] = None,
        limite: Annotated[int, Query(ge=1, le=LIMITE_DA_PAGINA)] = 25,
        cursor: Annotated[str | None, LinhaDaConsulta(500)] = None,
    ) -> JSONResponse:
        """As inserções de uma marca no mesmo filtro do relatório, na ordem do vídeo e do
        tempo, uma página por vez (o cursor da próxima em `X-Proximo-Cursor`)."""
        programa = programa or None
        tipo = tipo or None
        desde, ate = periodo
        fonte = _confere(programa, desde, ate, tipo)
        depois = posicao_do_cursor(cursor)
        lidas = ou_503(
            lambda: fonte.lista_da_marca(
                marca, programa, desde, ate, tipo, depois, limite
            )
        )
        lista, cabecalhos = recorta(lidas, depois, limite)
        poe_o_nome_dos_videos(lista, repositorio)
        return JSONResponse(
            [i.model_dump(mode="json") for i in lista], headers=cabecalhos
        )

    return rotas
