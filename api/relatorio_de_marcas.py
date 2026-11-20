"""Relatório por marca e por tipo de inserção (#267): `GET /v1/relatorios/marcas`.

Lê da cópia no BigQuery (#260) as linhas `comercial`, uma por inserção. Por marca, soma o
número de inserções, o tempo (a soma das durações, sem unir sobreposições: uma marca
incidental durante o merchan conta nas duas) e o número de vídeos; o detalhe por tipo de
inserção e a lista das inserções, com o vídeo e o tempo, vêm junto. A base (permissão,
filtros, CSV, erros) é a de `api.relatorios`, a mesma do tempo de tela. A soma é feita no
BigQuery (#363): ele devolve uma linha por marca, tipo de inserção e vídeo, com os
intervalos das inserções; o Python só monta a resposta.

A marca é a do catálogo, não o texto da linha: grafias que só diferem em maiúscula, acento,
pontuação ou espaço contam como uma, e o nome ou apelido de uma marca do catálogo conta como
ela, inclusive nos vídeos antigos, sem reprocessar (`api.marcas.MarcasCanonicas`). Fora do
catálogo, o rótulo é a grafia mais frequente do grupo (pelo número de inserções).
"""

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Annotated, Any, Literal, NamedTuple, Protocol, get_args

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.cache_curto import CacheCurto
from api.copia_bigquery import (
    ConfigDoBigQuery,
    CopiaEmMemoria,
    Transporte,
    parametro_de_lista,
)
from api.csv_seguro import csv_em_texto
from api.decupagem import Comercial
from api.erros import lido
from api.jobs import programas_do_pedido
from api.lixeira_na_leitura import PurgasDeMarca
from api.marcas import CatalogoDeMarcas, MarcasCanonicas
from api.modelo_do_job import RepositorioDeJobs
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
from api.texto import chave_da_marca
from api.texto_como_dado import Linha, LinhaDaConsulta

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
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        tipos: tuple[str, ...],
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
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        tipos: tuple[str, ...],
    ) -> list[Insercao]:
        achadas: list[Insercao] = []
        for x in linhas_da_copia(self._copia, ("comercial",), programas, desde, ate):
            if (
                x.marca
                and x.tipo_de_insercao
                and (not tipos or x.tipo_de_insercao in tipos)
            ):
                achadas.append(
                    Insercao(
                        x.job_id, x.marca, x.tipo_de_insercao, x.inicio_ms, x.fim_ms
                    )
                )
        return achadas

    def somas(
        self,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        tipos: tuple[str, ...],
    ) -> list[InsercoesDaMarca]:
        return somar(self.insercoes(programas, desde, ate, tipos))


def ranking_em_python(
    somas: list[InsercoesDaMarca], depois: int, limite: int
) -> "tuple[list[MarcaResumida], TotalDasMarcas]":
    """O ranking e os totais do período, a partir das somas; a página vai de `depois`
    a `limite + 1` itens (o que passa do limite diz que há mais)."""
    marcas = _linhas(somas)
    total = TotalDasMarcas(
        marcas=len(marcas),
        insercoes=sum(m.insercoes for m in marcas),
        tempo_ms=sum(m.tempo_ms for m in marcas),
        videos=len({s.job_id for s in somas}),
    )
    pagina = marcas[depois : depois + limite + 1]
    return [MarcaResumida(**m._asdict()) for m in pagina], total


def lista_em_python(
    dela: list[InsercoesDaMarca], depois: int, limite: int
) -> "list[InsercaoNoRelatorio]":
    """As inserções de uma marca, na ordem do relatório, a partir das somas dela (todas com
    o mesmo rótulo); a página vai de `depois` a `limite + 1` itens."""
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
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        tipos: tuple[str, ...],
    ) -> list[InsercoesDaMarca]:
        # Marca ou tipo vazio também fica de fora, como no dublê.
        condicoes = [
            "NULLIF(t.marca, '') IS NOT NULL",
            "NULLIF(t.tipo_de_insercao, '') IS NOT NULL",
        ]
        parametros = []
        if tipos:
            condicoes.append("t.tipo_de_insercao IN UNNEST(@tipos_de_insercao)")
            parametros.append(parametro_de_lista("tipos_de_insercao", tipos))
        linhas = consultar_no_bigquery(
            self._config,
            self._transporte,
            colunas=(
                "t.job_id, t.marca, t.tipo_de_insercao AS tipo, t.inicio_ms, t.fim_ms"
            ),
            tipos=("comercial",),
            programas=programas,
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
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        tipos: tuple[str, ...],
    ) -> list[InsercoesDaMarca]:
        return self._cache.obter(
            ("marcas", programas, desde, ate, tipos),
            lambda: self._consulta.somas(programas, desde, ate, tipos),
        )


class SoMarcasQueContam:
    """A lixeira do catálogo vale na hora (#593): tira das somas, antes do ranking, dos
    totais, das posições e da paginação, o texto que bate com o nome ou apelido de uma marca
    na lixeira, com o catálogo lido a cada consulta. A soma de baixo (e seu cache) não muda.

    A marca purgada (#595) deixa um registro: as ocorrências do nome em vídeos de Jobs
    criados até o instante da purga ficam fora, as dos criados depois contam. A data vem de
    `Job.criado_em` no Firestore (não muda com o reprocessamento nem com a recópia), lida em
    lote, uma vez por vídeo, só para as somas que batem com um registro; Job ausente conta
    como anterior; falha de leitura é erro (503), não "Job ausente". O vídeo na lixeira
    sai também (#619), depois do cache das somas.

    Tudo vale pela chave da marca (`chave_da_marca`): a lixeira e a purga cortam todas as
    grafias que só diferem em maiúscula, acento, pontuação ou espaço. Depois do corte, o
    texto vira o rótulo da marca (`MarcasCanonicas`), num ponto só: ranking, somas, CSV e a
    lista da marca saem dele. O catálogo é lido uma vez por operação."""

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

    def somas(
        self,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        tipos: tuple[str, ...],
    ) -> list[InsercoesDaMarca]:
        return self._com_rotulos(
            self._que_contam(self._consulta.somas(programas, desde, ate, tipos))
        )

    def insercoes_dos_nomes(self, nomes: set[str]) -> int:
        """Quantas inserções de todo o histórico, com o texto em `nomes` (nome e apelidos
        da marca; só a chave deles conta), o relatório contaria se a marca não estivesse na
        lixeira (#597): as somas sem a exclusão da lixeira, só com o corte das purgas. Cada
        inserção é uma linha da cópia, com ou sem vínculo no catálogo, então conta uma vez."""
        chaves = {chave_da_marca(n) for n in nomes}
        somas = self._consulta.somas((), None, None, ())
        return sum(
            s.insercoes
            for s in self._que_contam(
                [s for s in somas if chave_da_marca(s.marca) in chaves],
                so_a_purga=True,
            )
        )

    def _que_contam(
        self, somas: list[InsercoesDaMarca], *, so_a_purga: bool = False
    ) -> list[InsercoesDaMarca]:
        # O vídeo na lixeira não conta (#619), lido uma vez por operação (também no impacto).
        na_lixeira = ids_dos_jobs_na_lixeira(self._jobs)
        somas = [s for s in somas if s.job_id not in na_lixeira]
        # Um Quem conta por operação. O corte vale por texto, antes do agrupamento (que
        # vem depois, em `_com_rotulos`); `Cortes` compara pela chave.
        cortes = QuemConta(marcas=self._marcas, purgas=self._purgas).cortes(
            {s.marca for s in somas}, so_a_purga=so_a_purga
        )
        cortadas = [s for s in somas if cortes.tem_corte(s.marca)]
        criados = (
            {
                j.id: j.criado_em
                for j in lido(
                    lambda: self._jobs.obter_varios({s.job_id for s in cortadas})
                )
            }
            if cortadas
            else {}
        )
        return [s for s in somas if cortes.conta(s.marca, criados.get(s.job_id))]

    def _canonicas(self) -> MarcasCanonicas:
        return MarcasCanonicas(lido(self._marcas.todas))

    def _com_rotulos(
        self,
        somas: list[InsercoesDaMarca],
        canonicas: MarcasCanonicas | None = None,
    ) -> list[InsercoesDaMarca]:
        """A marca de cada soma vira o rótulo canônico: o nome no catálogo ou, fora dele, a
        grafia com mais inserções do grupo."""
        pesos: dict[str, int] = defaultdict(int)
        for s in somas:
            pesos[s.marca] += s.insercoes
        rotulos = (canonicas or self._canonicas()).rotulos(pesos)
        return [replace(s, marca=rotulos[s.marca]) for s in somas]

    def ranking(
        self,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        tipos: tuple[str, ...],
        depois: int,
        limite: int,
    ) -> "tuple[list[MarcaResumida], TotalDasMarcas]":
        return ranking_em_python(
            self.somas(programas, desde, ate, tipos), depois, limite
        )

    def lista_da_marca(
        self,
        marca: str,
        programas: Sequence[str],
        desde: date | None,
        ate: date | None,
        tipos: tuple[str, ...],
        depois: int,
        limite: int,
    ) -> "list[InsercaoNoRelatorio]":
        # `marca` é o rótulo que o relatório mostrou. Só a marca pedida passa pela regra: os
        # Jobs lidos são só os dos vídeos dela (todas as grafias do grupo).
        canonicas = self._canonicas()
        grupo = canonicas.grupo(marca)
        somas = self._consulta.somas(programas, desde, ate, tipos)
        dela = self._que_contam([s for s in somas if canonicas.grupo(s.marca) == grupo])
        return lista_em_python(self._com_rotulos(dela, canonicas), depois, limite)


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

    programas: list[str]
    desde: date | None
    ate: date | None
    tipos: list[str]
    total: TotalDasMarcas
    marcas: list[MarcaResumida]


class RelatorioDeMarcas(BaseModel):
    programas: list[str]
    desde: date | None
    ate: date | None
    tipos: list[str]
    marcas: list[MarcaNoRelatorio]


# Cada `tipo` repetido é uma linha só, com tamanho máximo.
TipoDoPedido = Annotated[str, Linha(40)]


def tipos_do_pedido(tipo: list[str] | None) -> tuple[str, ...]:
    """Os tipos marcados do `tipo` repetido, na ordem de `TIPOS_DE_INSERCAO` e sem repetir;
    vazio ou ausente é "todos" (tupla vazia). Valor fora da lista: 422."""
    pedidos = {t for t in tipo or [] if t}
    if desconhecido := next(
        (t for t in sorted(pedidos) if t not in TIPOS_DE_INSERCAO), None
    ):
        raise HTTPException(422, f"Tipo de inserção desconhecido: {desconhecido}")
    return tuple(t for t in TIPOS_DE_INSERCAO if t in pedidos)


def _ordem_dos_tipos(tipos: set[str]) -> list[str]:
    return [t for t in TIPOS_DE_INSERCAO if t in tipos] + sorted(
        tipos - set(TIPOS_DE_INSERCAO)
    )


class _Linha(NamedTuple):
    """Uma marca no ranking, sem a lista das inserções: o que o ranking, os totais e o
    CSV usam."""

    marca: str
    insercoes: int
    tempo_ms: int
    videos: int
    por_tipo: list[TotalPorTipo]


def _linhas(somas: list[InsercoesDaMarca]) -> list[_Linha]:
    """Uma linha por marca, do maior tempo para o menor; o detalhe por tipo segue a ordem
    de `TIPOS_DE_INSERCAO` (um tipo que a decupagem não tem mais, de uma linha antiga, vem
    no fim, para as partes fecharem com o total). Só tuplas e números: sem um objeto por
    inserção."""
    # por marca e por tipo: inserções, tempo e os vídeos
    por_marca: dict[str, dict[str, tuple[list[int], set[str]]]] = {}
    for g in somas:
        tipos = por_marca.setdefault(g.marca, {})
        soma, videos = tipos.setdefault(g.tipo, ([0, 0], set()))
        soma[0] += g.insercoes
        soma[1] += g.tempo_ms
        videos.add(g.job_id)
    linhas = [
        _Linha(
            marca,
            sum(s[0] for s, _ in tipos.values()),
            sum(s[1] for s, _ in tipos.values()),
            len(set().union(*(v for _, v in tipos.values()))),
            [
                TotalPorTipo(
                    tipo=t,
                    insercoes=tipos[t][0][0],
                    tempo_ms=tipos[t][0][1],
                    videos=len(tipos[t][1]),
                )
                for t in _ordem_dos_tipos(set(tipos))
            ],
        )
        for marca, tipos in por_marca.items()
    ]
    linhas.sort(key=lambda m: (-m.tempo_ms, m.marca))
    return linhas


def relatorio(somas: list[InsercoesDaMarca]) -> list[MarcaNoRelatorio]:
    """O ranking de `_linhas`, cada marca com a lista das inserções, a do vídeo e do tempo
    (no empate, a do tipo); os objetos por inserção só nascem aqui, no JSON completo e na
    lista de uma marca."""
    por_marca: dict[str, list[InsercaoNoRelatorio]] = defaultdict(list)
    for g in somas:
        por_marca[g.marca] += [
            InsercaoNoRelatorio(job_id=g.job_id, tipo=g.tipo, inicio_ms=ini, fim_ms=fim)
            for ini, fim in g.intervalos
        ]
    for lista in por_marca.values():
        lista.sort(key=lambda i: (i.job_id, i.inicio_ms, i.fim_ms, i.tipo))
    return [
        MarcaNoRelatorio(**m._asdict(), lista=por_marca[m.marca])
        for m in _linhas(somas)
    ]


def em_csv(marcas: Sequence[MarcaResumida | _Linha]) -> str:
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

    @rotas.get("/marcas", response_model=RelatorioDeMarcas | RankingDeMarcas)
    def marcas(
        _pessoa: PodeVerORelatorio,
        periodo: Annotated[Periodo, Depends(no_periodo)],
        programa: Annotated[list[ProgramaDoPedido] | None, Query()] = None,
        tipo: Annotated[list[TipoDoPedido] | None, Query()] = None,
        formato: Literal["json", "csv"] = "json",
        limite: Annotated[int | None, Query(ge=1, le=LIMITE_DA_PAGINA)] = None,
        cursor: Annotated[str | None, LinhaDaConsulta(500)] = None,
    ) -> Any:
        """`desde` e `ate` são datas de exibição, as duas inclusive; sem `programa` e sem `tipo` (ou só vazios), todos; os dois se repetem, um
        por valor marcado. Com `limite`, uma página do ranking (sem a lista das inserções, com os totais do período) e o cursor da
        próxima em `X-Proximo-Cursor`; as inserções de uma marca ficam em
        `/marcas/insercoes`. O CSV vem sempre inteiro."""
        programas = programas_do_pedido(programa)
        tipos = tipos_do_pedido(tipo)
        desde, ate = periodo
        fonte = confere_o_pedido(com_lixeira, desde, ate)
        if limite is not None and formato == "json":
            depois = posicao_do_cursor(cursor)
            lidas, total = ou_503(
                lambda: fonte.ranking(programas, desde, ate, tipos, depois, limite)
            )
            pagina, cabecalhos = recorta(lidas, depois, limite)
            corpo = RankingDeMarcas(
                programas=list(programas),
                desde=desde,
                ate=ate,
                tipos=list(tipos),
                total=total,
                marcas=pagina,
            )
            return JSONResponse(corpo.model_dump(mode="json"), headers=cabecalhos)
        somas = ou_503(lambda: fonte.somas(programas, desde, ate, tipos))
        if formato == "csv":
            return resposta_em_csv(em_csv(_linhas(somas)), "marcas.csv")
        achadas = relatorio(somas)
        poe_o_nome_dos_videos((i for m in achadas for i in m.lista), repositorio)
        return RelatorioDeMarcas(
            programas=list(programas),
            desde=desde,
            ate=ate,
            tipos=list(tipos),
            marcas=achadas,
        )

    @rotas.get("/marcas/insercoes", response_model=list[InsercaoNoRelatorio])
    def lista_da_marca(
        _pessoa: PodeVerORelatorio,
        periodo: Annotated[Periodo, Depends(no_periodo)],
        marca: Annotated[str, LinhaDaConsulta(200, min_length=1)],
        programa: Annotated[list[ProgramaDoPedido] | None, Query()] = None,
        tipo: Annotated[list[TipoDoPedido] | None, Query()] = None,
        limite: Annotated[int, Query(ge=1, le=LIMITE_DA_PAGINA)] = 25,
        cursor: Annotated[str | None, LinhaDaConsulta(500)] = None,
    ) -> JSONResponse:
        """As inserções de uma marca no mesmo filtro do relatório, na ordem do vídeo e do
        tempo, uma página por vez (o cursor da próxima em `X-Proximo-Cursor`)."""
        programas = programas_do_pedido(programa)
        tipos = tipos_do_pedido(tipo)
        desde, ate = periodo
        fonte = confere_o_pedido(com_lixeira, desde, ate)
        depois = posicao_do_cursor(cursor)
        lidas = ou_503(
            lambda: fonte.lista_da_marca(
                marca, programas, desde, ate, tipos, depois, limite
            )
        )
        lista, cabecalhos = recorta(lidas, depois, limite)
        poe_o_nome_dos_videos(lista, repositorio)
        return JSONResponse(
            [i.model_dump(mode="json") for i in lista], headers=cabecalhos
        )

    return rotas
