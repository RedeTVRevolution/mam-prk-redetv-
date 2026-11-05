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
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal, Protocol, get_args

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.copia_bigquery import ConfigDoBigQuery, CopiaEmMemoria, Transporte, _parametro
from api.decupagem import Comercial
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


# O que vem depois de `WITH base AS (...)`: uma linha por marca, tipo e vídeo.
SOMA_EM_SQL = """SELECT marca, tipo, job_id, COUNT(*), SUM(fim_ms - inicio_ms),
  TO_JSON_STRING(ARRAY_AGG(STRUCT(inicio_ms, fim_ms) ORDER BY inicio_ms, fim_ms))
FROM base
GROUP BY marca, tipo, job_id"""


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
        parametros: list[dict[str, Any]] = []
        if tipo is not None:
            condicoes.append("t.tipo_de_insercao = @tipo_de_insercao")
            parametros.append(_parametro("tipo_de_insercao", tipo))
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
        return [
            InsercoesDaMarca(
                marca=v[0],
                tipo=v[1],
                job_id=v[2],
                insercoes=int(v[3]),
                tempo_ms=int(v[4]),
                intervalos=[
                    (int(i["inicio_ms"]), int(i["fim_ms"])) for i in json.loads(v[5])
                ],
            )
            for v in linhas
        ]


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


class MarcaNoRelatorio(BaseModel):
    marca: str
    insercoes: int
    tempo_ms: int
    videos: int
    por_tipo: list[TotalPorTipo]
    lista: list[InsercaoNoRelatorio]


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


def relatorio(somas: list[InsercoesDaMarca]) -> list[MarcaNoRelatorio]:
    """Uma linha por marca, do maior tempo para o menor; o detalhe por tipo segue a ordem
    de `TIPOS_DE_INSERCAO` (um tipo que a decupagem não tem mais, de uma linha antiga, vem
    no fim, para as partes fecharem com o total) e a lista das inserções, a do vídeo e do
    tempo."""
    por_marca: dict[str, list[InsercoesDaMarca]] = defaultdict(list)
    for g in somas:
        por_marca[g.marca].append(g)
    marcas: list[MarcaNoRelatorio] = []
    for marca, dela in por_marca.items():
        total = _total(TIPO_DO_TOTAL, dela)
        tipos = {g.tipo for g in dela}
        ordem = [t for t in TIPOS_DE_INSERCAO if t in tipos]
        ordem += sorted(tipos - set(TIPOS_DE_INSERCAO))
        lista = [
            InsercaoNoRelatorio(job_id=g.job_id, tipo=g.tipo, inicio_ms=ini, fim_ms=fim)
            for g in dela
            for ini, fim in g.intervalos
        ]
        lista.sort(key=lambda i: (i.job_id, i.inicio_ms, i.fim_ms))
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
    consulta: ConsultaDeInsercoes | None, repositorio: RepositorioDeJobs
) -> APIRouter:
    rotas = APIRouter(prefix="/relatorios")

    @rotas.get("/marcas", response_model=RelatorioDeMarcas)
    def marcas(
        _pessoa: PodeVerORelatorio,
        programa: Annotated[str | None, Query(max_length=100)] = None,
        desde: date | None = None,
        ate: date | None = None,
        tipo: Annotated[str | None, Query(max_length=40)] = None,
        formato: Literal["json", "csv"] = "json",
    ) -> Any:
        """`desde` e `ate` são datas de exibição, as duas inclusive; sem programa (ou com
        `programa=` vazio) e sem tipo (ou vazio), todos."""
        programa = programa or None
        tipo = tipo or None
        if tipo is not None and tipo not in TIPOS_DE_INSERCAO:
            raise HTTPException(422, f"Tipo de inserção desconhecido: {tipo}")
        fonte = confere_o_pedido(consulta, desde, ate)
        achadas = ou_503(lambda: relatorio(fonte.somas(programa, desde, ate, tipo)))
        if formato == "csv":
            return resposta_em_csv(em_csv(achadas), "marcas.csv")
        poe_o_nome_dos_videos((i for m in achadas for i in m.lista), repositorio)
        return RelatorioDeMarcas(
            programa=programa, desde=desde, ate=ate, tipo=tipo, marcas=achadas
        )

    return rotas
