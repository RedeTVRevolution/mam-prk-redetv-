"""Relatório de tempo de tela por pessoa (#266): `GET /v1/relatorios/tempo-de-tela`.

Lê da cópia no BigQuery (#260) as linhas `aparicao`, `mencao_na_fala` e `mencao_no_texto`.
Só a aparição (a pessoa visível) soma tempo de tela; as menções entram só como contagem.
Aparições da mesma pessoa no mesmo vídeo que se sobrepõem ou se tocam viram uma só.
A consulta filtra no BigQuery por programa e data de exibição; a união dos intervalos é
feita aqui, sobre as linhas que voltam. Um período grande demais para uma resposta só
(10 MB) falha alto: peça um período menor.
"""

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


class ConsultaDeMomentos(Protocol):
    def momentos(
        self, programa: str | None, desde: date | None, ate: date | None
    ) -> list[MomentoDaPessoa]:
        """Os momentos das pessoas; `desde` e `ate` são datas de exibição, inclusive."""


class ConsultaEmMemoria:
    """Dublê da consulta: os mesmos filtros sobre a cópia em memória."""

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


class ConsultaBigQuery:
    """A consulta real: REST com o mesmo transporte da cópia."""

    def __init__(self, config: ConfigDoBigQuery, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def momentos(
        self, programa: str | None, desde: date | None, ate: date | None
    ) -> list[MomentoDaPessoa]:
        linhas = consultar_no_bigquery(
            self._config,
            self._transporte,
            colunas="t.job_id, p.id, p.nome, t.tipo, t.inicio_ms, t.fim_ms",
            tipos=TIPOS_DO_RELATORIO,
            programa=programa,
            desde=desde,
            ate=ate,
            unnest_das_pessoas=True,
            condicoes=["p.id IS NOT NULL"],
        )
        return [
            MomentoDaPessoa(v[0], v[1], v[2] or "", v[3], int(v[4]), int(v[5]))
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


def _uniao(intervalos: list[tuple[int, int]]) -> list[tuple[int, int]]:
    unidos: list[tuple[int, int]] = []
    for inicio, fim in sorted(intervalos):
        if unidos and inicio <= unidos[-1][1]:
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], fim))
        else:
            unidos.append((inicio, fim))
    return unidos


def relatorio(momentos: list[MomentoDaPessoa]) -> list[PessoaNoRelatorio]:
    """Uma linha por pessoa, do maior tempo de tela para o menor.

    A pessoa é o id do catálogo; o nome é o que mais aparece nas linhas dela (um vídeo
    copiado antes de uma correção de grafia não parte a pessoa em duas).
    """
    por_pessoa: dict[str, list[MomentoDaPessoa]] = defaultdict(list)
    for m in momentos:
        por_pessoa[m.pessoa_id].append(m)
    pessoas: list[PessoaNoRelatorio] = []
    for pessoa_id, dela in por_pessoa.items():
        contagem = Counter(m.nome for m in dela)
        nome = min(contagem, key=lambda n: (-contagem[n], n))
        por_job: dict[str, list[MomentoDaPessoa]] = defaultdict(list)
        for m in dela:
            por_job[m.job_id].append(m)
        videos: list[VideoDaPessoa] = []
        for job_id, do_video in por_job.items():
            aparicoes = _uniao(
                [(m.inicio_ms, m.fim_ms) for m in do_video if m.tipo == "aparicao"]
            )
            videos.append(
                VideoDaPessoa(
                    job_id=job_id,
                    tempo_de_tela_ms=sum(fim - ini for ini, fim in aparicoes),
                    aparicoes=len(aparicoes),
                    mencoes_na_fala=sum(m.tipo == "mencao_na_fala" for m in do_video),
                    mencoes_no_texto=sum(m.tipo == "mencao_no_texto" for m in do_video),
                )
            )
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


def criar_rotas_dos_relatorios(
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
        pessoas = ou_503(lambda: relatorio(fonte.momentos(programa, desde, ate)))
        if formato == "csv":
            return resposta_em_csv(em_csv(pessoas), "tempo-de-tela.csv")
        nomes: dict[str, str | None] = {}
        for p in pessoas:
            for v in p.por_video:
                if v.job_id not in nomes:
                    job = repositorio.obter(v.job_id)
                    nomes[v.job_id] = job.nome if job else None
                v.nome = nomes[v.job_id]
        return RelatorioDeTempoDeTela(
            programa=programa, desde=desde, ate=ate, pessoas=pessoas
        )

    return rotas
