"""Relatório por marca e por tipo de inserção (#267): `GET /v1/relatorios/marcas`.

Lê da cópia no BigQuery (#260) as linhas `comercial`, uma por inserção. Por marca, soma o
número de inserções, o tempo (a soma das durações, sem unir sobreposições: uma marca
incidental durante o merchan conta nas duas) e o número de vídeos; o detalhe por tipo de
inserção e a lista das inserções, com o vídeo e o tempo, vêm junto. A base (permissão,
filtros, CSV, erros) é a de `api.relatorios`, a mesma do tempo de tela.
"""

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


class ConsultaDeInsercoes(Protocol):
    def insercoes(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
    ) -> list[Insercao]:
        """As inserções com marca; `desde` e `ate` são datas de exibição, inclusive."""


class ConsultaEmMemoria:
    """Dublê da consulta: os mesmos filtros sobre a cópia em memória."""

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


class ConsultaBigQuery:
    """A consulta real: REST com o mesmo transporte da cópia."""

    def __init__(self, config: ConfigDoBigQuery, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def insercoes(
        self,
        programa: str | None,
        desde: date | None,
        ate: date | None,
        tipo: str | None,
    ) -> list[Insercao]:
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
            colunas="t.job_id, t.marca, t.tipo_de_insercao, t.inicio_ms, t.fim_ms",
            tipos=("comercial",),
            programa=programa,
            desde=desde,
            ate=ate,
            condicoes=condicoes,
            parametros=parametros,
        )
        return [Insercao(v[0], v[1], v[2], int(v[3]), int(v[4])) for v in linhas]


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


def _total(tipo: str, itens: list[Insercao]) -> TotalPorTipo:
    return TotalPorTipo(
        tipo=tipo,
        insercoes=len(itens),
        tempo_ms=sum(i.fim_ms - i.inicio_ms for i in itens),
        videos=len({i.job_id for i in itens}),
    )


def relatorio(insercoes: list[Insercao]) -> list[MarcaNoRelatorio]:
    """Uma linha por marca, do maior tempo para o menor; o detalhe por tipo segue a ordem
    de `TIPOS_DE_INSERCAO` (um tipo que a decupagem não tem mais, de uma linha antiga, vem
    no fim, para as partes fecharem com o total) e a lista das inserções, a do vídeo e do
    tempo."""
    por_marca: dict[str, list[Insercao]] = defaultdict(list)
    for i in insercoes:
        por_marca[i.marca].append(i)
    marcas: list[MarcaNoRelatorio] = []
    for marca, dela in por_marca.items():
        total = _total(TIPO_DO_TOTAL, dela)
        tipos = {i.tipo for i in dela}
        ordem = [t for t in TIPOS_DE_INSERCAO if t in tipos]
        ordem += sorted(tipos - set(TIPOS_DE_INSERCAO))
        marcas.append(
            MarcaNoRelatorio(
                marca=marca,
                insercoes=total.insercoes,
                tempo_ms=total.tempo_ms,
                videos=total.videos,
                por_tipo=[_total(t, [i for i in dela if i.tipo == t]) for t in ordem],
                lista=[
                    InsercaoNoRelatorio(
                        job_id=i.job_id,
                        tipo=i.tipo,
                        inicio_ms=i.inicio_ms,
                        fim_ms=i.fim_ms,
                    )
                    for i in sorted(
                        dela, key=lambda i: (i.job_id, i.inicio_ms, i.fim_ms)
                    )
                ],
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
        achadas = ou_503(lambda: relatorio(fonte.insercoes(programa, desde, ate, tipo)))
        if formato == "csv":
            return resposta_em_csv(em_csv(achadas), "marcas.csv")
        poe_o_nome_dos_videos((i for m in achadas for i in m.lista), repositorio)
        return RelatorioDeMarcas(
            programa=programa, desde=desde, ate=ate, tipo=tipo, marcas=achadas
        )

    return rotas
