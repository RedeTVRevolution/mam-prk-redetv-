"""Relatório de tempo de tela por pessoa (#266): `GET /v1/relatorios/tempo-de-tela`.

Lê da cópia no BigQuery (#260) as linhas `aparicao`, `mencao_na_fala` e `mencao_no_texto`.
Só a aparição (a pessoa visível) soma tempo de tela; as menções entram só como contagem.
Aparições da mesma pessoa no mesmo vídeo que se sobrepõem ou se tocam viram uma só.
A consulta filtra no BigQuery por programa e data de exibição; a união dos intervalos é
feita aqui, sobre as linhas que voltam. Um período grande demais para uma resposta só
(10 MB) falha alto: peça um período menor.
"""

import csv
import io
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from api.auth import ChamadorAutenticado, Usuario
from api.copia_bigquery import (
    TIPOS_DAS_PESSOAS,
    ConfigDoBigQuery,
    CopiaEmMemoria,
    Transporte,
    _parametro,
    transporte_http,
)
from api.jobs import RepositorioDeJobs, _confere_permissao

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
        achados: list[MomentoDaPessoa] = []
        for linhas in self._copia.por_job.values():
            for x in linhas:
                dia = x.data_de_exibicao
                if x.tipo not in TIPOS_DO_RELATORIO:
                    continue
                if programa is not None and x.programa != programa:
                    continue
                if (desde or ate) and dia is None:
                    continue
                if (desde and dia and dia < desde) or (ate and dia and dia > ate):
                    continue
                achados += [
                    MomentoDaPessoa(
                        x.job_id, p.id, p.nome, x.tipo, x.inicio_ms, x.fim_ms
                    )
                    for p in x.pessoas
                ]
        return achados


class ConsultaBigQuery:
    """A consulta real: REST com o mesmo transporte da cópia."""

    def __init__(self, config: ConfigDoBigQuery, transporte: Transporte) -> None:
        self._config = config
        self._transporte = transporte

    def momentos(
        self, programa: str | None, desde: date | None, ate: date | None
    ) -> list[MomentoDaPessoa]:
        c = self._config
        tipos = ", ".join(f"'{t}'" for t in TIPOS_DO_RELATORIO)
        condicoes = [f"t.tipo IN ({tipos})", "p.id IS NOT NULL"]
        parametros: list[dict[str, Any]] = []
        if programa is not None:
            condicoes.append("t.programa = @programa")
            parametros.append(_parametro("programa", programa))
        for nome, dia, comparacao in (("desde", desde, ">="), ("ate", ate, "<=")):
            if dia is not None:
                condicoes.append(f"t.data_de_exibicao {comparacao} @{nome}")
                parametros.append(_parametro(nome, dia.isoformat(), "DATE"))
        consulta = (
            "SELECT t.job_id, p.id, p.nome, t.tipo, t.inicio_ms, t.fim_ms\n"
            f"FROM `{c.projeto}.{c.dataset}.{c.tabela}` AS t, UNNEST(t.pessoas) AS p\n"
            f"WHERE {' AND '.join(condicoes)}"
        )
        resposta = self._transporte(
            {
                "query": consulta,
                "useLegacySql": False,
                "location": c.regiao,
                "timeoutMs": 60_000,
                "maxResults": 100_000,
                "queryParameters": parametros,
            }
        )
        if not resposta.get("jobComplete", False):
            raise RuntimeError("consulta do tempo de tela não terminou no prazo")
        if resposta.get("pageToken"):
            raise RuntimeError(
                "o relatório não cabe numa resposta: peça um período menor"
            )
        achados: list[MomentoDaPessoa] = []
        for linha in resposta.get("rows", []):
            v = [campo["v"] for campo in linha["f"]]
            achados.append(
                MomentoDaPessoa(v[0], v[1], v[2] or "", v[3], int(v[4]), int(v[5]))
            )
        return achados


def consulta_do_ambiente(ambiente: Any) -> ConsultaBigQuery | None:
    """A consulta configurada, ou `None` se o ambiente não diz onde a cópia mora."""
    if "BIGQUERY_DATASET" not in ambiente:
        return None
    config = ConfigDoBigQuery.do_ambiente(ambiente)
    return ConsultaBigQuery(config, transporte_http(config.projeto))


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


def _celula(texto: str) -> str:
    """O nome que começa como fórmula não vira fórmula na planilha."""
    return f"'{texto}" if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def em_csv(pessoas: list[PessoaNoRelatorio]) -> str:
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(COLUNAS_DO_CSV)
    for p in pessoas:
        escritor.writerow(
            [
                p.pessoa_id,
                _celula(p.nome),
                p.tempo_de_tela_ms,
                p.videos,
                p.aparicoes,
                p.mencoes_na_fala,
                p.mencoes_no_texto,
            ]
        )
    return saida.getvalue()


def _exige_ver_o_relatorio(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: pessoa com `decupagem.ver`. A cópia não guarda o sistema dono do
    vídeo, então uma chave de sistema veria os vídeos dos outros: não consulta."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não consulta o relatório")
    _confere_permissao(request, chamador, "decupagem.ver")
    return chamador


def criar_rotas_dos_relatorios(
    consulta: ConsultaDeMomentos | None, repositorio: RepositorioDeJobs
) -> APIRouter:
    rotas = APIRouter(prefix="/relatorios")

    @rotas.get("/tempo-de-tela", response_model=RelatorioDeTempoDeTela)
    def tempo_de_tela(
        _pessoa: Annotated[Usuario, Depends(_exige_ver_o_relatorio)],
        programa: Annotated[str | None, Query(max_length=100)] = None,
        desde: date | None = None,
        ate: date | None = None,
        formato: Literal["json", "csv"] = "json",
    ) -> Any:
        """`desde` e `ate` são datas de exibição, as duas inclusive; sem programa
        (ou com `programa=` vazio), todos."""
        programa = programa or None
        if consulta is None:
            raise HTTPException(503, "O BigQuery não está configurado neste ambiente")
        if desde and ate and desde > ate:
            raise HTTPException(422, "`desde` não pode ser depois de `ate`")
        try:
            pessoas = relatorio(consulta.momentos(programa, desde, ate))
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from e
        if formato == "csv":
            return Response(
                em_csv(pessoas),
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": 'attachment; filename="tempo-de-tela.csv"'
                },
            )
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
