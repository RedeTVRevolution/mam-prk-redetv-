"""Busca (#120): a consulta entendida vira cláusulas no índice, que voltam fundidas por RRF,
reordenadas, juntadas em trechos e agrupadas por vídeo.

Os filtros do servidor (permissão, lixeira) entram por cima de tudo o que vem da consulta
(`com_filtros_do_servidor`); nomes de campo e operadores são fixos no código, e o texto
do usuário só chega ao índice como texto puro.
"""

import logging
import time
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Collection
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timedelta
from itertools import zip_longest
from typing import Literal, Protocol

from pydantic import BaseModel

from api.catalogo import Catalogo
from api.comparador import normalizar
from api.entendimento_da_consulta import (
    EVIDENCIAS,
    ConsultaEntendida,
    ModelArmor,
    entender,
)
from api.gemini import Transporte
from api.indice_da_busca import (
    Consulta,
    Filtros,
    IndiceDaBusca,
    Registro,
    TipoDeRegistro,
)
from api.jobs import Armazenamento, Job, RepositorioDeJobs

log = logging.getLogger(__name__)

RRF_K = 60
# Cada nível de destaque acima de 1 soma isto à pontuação do objeto do inventário: o
# destaque 3 (+6%) passa quem está logo atrás, uns três lugares no topo da lista (a
# pontuação é 1/(60+posição), então o ganho cresce para uns nove lugares na
# centésima posição), e não quem está bem mais acima. Registro sem destaque pesa 1.
PESO_POR_NIVEL_DE_DESTAQUE = 0.03
TETO_DE_REGISTROS = 100  # por cláusula
TETO_DE_VIDEOS = 50
VIDEOS_POR_PADRAO = 20
JUNCAO_MS = 3_000
VALIDADE_DO_QUADRO = timedelta(minutes=10)
# Valores mostrados por faceta: os de mais vídeos.
TETO_DE_VALORES_POR_FACETA = 20
ROTULO_DO_TIPO: dict[str, str] = {
    "plano": "Plano",
    "fala": "Fala",
    "texto_na_tela": "GC",
    "objeto": "Objeto",
}

Ordem = Literal["relevancia", "data"]
# As evidências que o editor liga e desliga: as quatro do modelo, mais objeto e marca.
EvidenciaDaBusca = Literal["imagem", "citada", "fala", "gc", "objeto", "marca"]


class Ranking(Protocol):
    """Porta da API de Ranking: reordena os registros pela consulta de texto livre."""

    def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]: ...


class RankingEmOrdem:
    """Dublê: mantém a ordem recebida."""

    def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]:
        return registros


class Destaque(BaseModel):
    """Posições `[inicio, fim)` no `motivo`, em caracteres; nunca HTML."""

    inicio: int
    fim: int


class Momento(BaseModel):
    inicio_ms: int
    fim_ms: int
    motivo: str
    destaques: list[Destaque]
    quadro_url: str | None


class VideoDoResultado(BaseModel):
    job_id: str
    nome: str
    programa: str | None
    data_exibicao: date | None
    duracao_s: float | None
    n_momentos: int
    momentos: list[Momento]


class SemAparicao(BaseModel):
    """A pessoa pedida não aparece na imagem no programa e período pedidos; quantas vezes é citada."""

    pessoa_id: str
    nome: str
    mencoes_na_fala: int
    mencoes_na_tela: int


class Entendida(BaseModel):
    """O que a busca usou da consulta: os chips e filtros que a tela mostra ligados."""

    evidencias: list[EvidenciaDaBusca]
    programa: str | None
    desde: date | None
    ate: date | None


@dataclass(frozen=True)
class Ajustes:
    """O que o editor mudou na tela, por cima do que o modelo entendeu."""

    evidencias: tuple[EvidenciaDaBusca, ...] = ()  # vazio: fica o entendido
    programa: str | None = None  # "": sem programa
    desde: date | None = None
    ate: date | None = None
    sem_periodo: bool = False  # tira o período entendido (o "Todos os anos" da tela)
    # Facetas da tela: filtram os candidatos (os de programa e mês são o programa e o período).
    pessoa: str | None = None  # id do catálogo: na imagem ou dona do objeto
    marca: str | None = None
    tipo: TipoDeRegistro | None = None


class ValorDaFaceta(BaseModel):
    """Um valor da faceta e em quantos vídeos dos candidatos ele aparece."""

    valor: str
    rotulo: str
    videos: int


class Facetas(BaseModel):
    """Contagens por faceta, sobre os candidatos que a busca trouxe (veja `_facetas`)."""

    programa: list[ValorDaFaceta] = []
    mes: list[ValorDaFaceta] = []
    pessoa: list[ValorDaFaceta] = []
    marca: list[ValorDaFaceta] = []
    tipo: list[ValorDaFaceta] = []


class ResultadoDaBusca(BaseModel):
    entendida: Entendida
    videos: list[VideoDoResultado]
    sem_aparicoes: list[SemAparicao]
    plano_b: bool
    facetas: Facetas
    quadros_expiram_em: datetime


def filtros_do_servidor() -> Filtros:
    """Os filtros que o servidor impõe a toda busca, acima da consulta.

    Hoje nenhum campo do índice carrega a permissão. O filtro "não está na lixeira" (#144)
    entra aqui; enquanto isso, `Busca` já descarta o vídeo cujo Job não está concluído.
    """
    return Filtros()


def com_filtros_do_servidor(da_consulta: Filtros, do_servidor: Filtros) -> Filtros:
    """Todo campo do servidor vale, e o da consulta só preenche o que ele deixou livre."""
    impostos = {
        f.name: getattr(do_servidor, f.name)
        for f in fields(Filtros)
        if getattr(do_servidor, f.name) is not None
    }
    return replace(da_consulta, **impostos)


@dataclass(frozen=True)
class _Clausula:
    consulta: Consulta
    motivo: Callable[[Registro], str]
    # A cláusula "na imagem" de uma pessoa: vazia, a resposta conta as menções dela.
    pessoa_na_imagem: str | None = None


def _sem_acento(texto: str) -> str:
    """Minúsculas e sem acento, um caractere por caractere (as posições se mantêm)."""
    return "".join(unicodedata.normalize("NFD", c)[0].lower() for c in texto)


def _destaques(texto: str, termos: Collection[str]) -> list[Destaque]:
    palheiro = _sem_acento(texto)
    achados: list[tuple[int, int]] = []
    for termo in {_sem_acento(t) for t in termos if len(t.strip()) >= 2}:
        i = palheiro.find(termo)
        while i != -1:
            achados.append((i, i + len(termo)))
            i = palheiro.find(termo, i + len(termo))
    unidos: list[list[int]] = []
    for inicio, fim in sorted(achados):
        if unidos and inicio <= unidos[-1][1]:
            unidos[-1][1] = max(unidos[-1][1], fim)
        else:
            unidos.append([inicio, fim])
    return [Destaque(inicio=i, fim=f) for i, f in unidos]


@dataclass
class _Trecho:
    job_id: str
    inicio_ms: int
    fim_ms: int
    motivo: str
    posicao: int  # a melhor posição, no resultado fundido, entre os registros juntados
    quadro: str | None


class Busca:
    def __init__(
        self,
        *,
        transporte: Transporte,
        catalogo: Catalogo,
        armor: ModelArmor,
        programas: Collection[str],
        indice: IndiceDaBusca,
        ranking: Ranking,
        repositorio: RepositorioDeJobs,
        armazenamento: Armazenamento,
        relogio: Callable[[], datetime],
    ) -> None:
        self._transporte = transporte
        self._catalogo = catalogo
        self._armor = armor
        self._programas = programas
        self._indice = indice
        self._ranking = ranking
        self._repositorio = repositorio
        self._armazenamento = armazenamento
        self._relogio = relogio

    def buscar(
        self,
        texto: str,
        *,
        ordem: Ordem = "relevancia",
        limite: int = VIDEOS_POR_PADRAO,
        filtros_do_servidor: Filtros | None = None,
        sistema: str | None = None,
        ajustes: Ajustes | None = None,
    ) -> ResultadoDaBusca:
        inicio = time.perf_counter()
        impostos = filtros_do_servidor or Filtros()
        entendida = _ajustada(
            entender(
                texto,
                transporte=self._transporte,
                catalogo=self._catalogo,
                armor=self._armor,
                programas=self._programas,
            ),
            ajustes or Ajustes(),
        )
        jobs: dict[str, Job | None] = {}

        def job(id: str) -> Job | None:
            if id not in jobs:
                achado = self._repositorio.obter(id)
                visivel = (
                    achado is not None
                    and achado.estado == "concluido"
                    and (sistema is None or achado.sistema == sistema)
                )
                jobs[id] = achado if visivel else None
            return jobs[id]

        def consultar(c: Consulta) -> list[Registro]:
            c = replace(
                c,
                filtros=com_filtros_do_servidor(c.filtros, impostos),
                limite=TETO_DE_REGISTROS,
            )
            return [r for r in self._indice.buscar(c) if job(r.job_id)]

        nomes: dict[str, str] = {}

        def nome(id: str | None) -> str | None:
            if id and id not in nomes:
                pessoa = self._catalogo.obter(id)
                nomes[id] = pessoa.nome if pessoa else ""
            return nomes.get(id or "") or None

        clausulas = self._clausulas(entendida, nome)
        facetado = ajustes or Ajustes()
        # As facetas vão ao índice, para não filtrar só o que coube no teto de registros;
        # o `_casa` confere o que o índice não exprime (duas pessoas na mesma cláusula).
        resultados = [
            [
                r
                for r in _intercalar(
                    [consultar(q) for q in _com_facetas(c.consulta, facetado)]
                )
                if _casa(r, facetado)
            ]
            for c in clausulas
        ]
        sem_facetas = all(
            x is None for x in (facetado.pessoa, facetado.marca, facetado.tipo)
        )
        fundidos = _fundir(resultados)
        achados = [r for r, _, _ in fundidos]
        # Sem a API de Ranking, a posição é a da pontuação do RRF: registros de mesma
        # pontuação empatam, e o desempate dos vídeos é o número de momentos.
        posicao = _posicoes_por_pontos(fundidos)
        if entendida.texto_livre and achados:
            try:
                achados = self._ranking.reordenar(entendida.texto_livre, achados)
                # A ordem do ranking, com o peso do destaque sobre a posição.
                posicao = _posicoes_por_pontos(
                    [(r, 0, _peso(r) / (RRF_K + i + 1)) for i, r in enumerate(achados)]
                )
            except Exception:
                log.exception("ranking indisponível; fica a ordem do índice")
        motivo_de = {r.id: clausulas[c].motivo(r) for r, c, _ in fundidos}
        termos = _termos(entendida, nome)
        trechos = _juntar([r for r in achados if r.id in motivo_de], motivo_de, posicao)
        videos = self._videos(trechos, job, termos, ordem)[:limite]
        vazios = [
            self._sem_aparicao(c.pessoa_na_imagem, entendida, consultar, nome)
            for c, achados_da_clausula in zip(clausulas, resultados, strict=True)
            # "Nenhuma aparição" fala do acervo, não do que a faceta deixou.
            if c.pessoa_na_imagem
            and not (achados_da_clausula if sem_facetas else consultar(c.consulta))
        ]
        log.info(
            "busca em %d ms: %d vídeos, %d clausulas%s",
            (time.perf_counter() - inicio) * 1000,
            len(videos),
            len(clausulas),
            ", plano B" if entendida.plano_b else "",
        )
        agora = self._relogio()
        return ResultadoDaBusca(
            entendida=Entendida(
                evidencias=_ligadas(entendida),
                programa=entendida.programa,
                desde=entendida.exibido_desde,
                ate=entendida.exibido_ate,
            ),
            videos=videos,
            sem_aparicoes=vazios,
            plano_b=entendida.plano_b,
            facetas=_facetas([r for r, _, _ in fundidos], nome),
            quadros_expiram_em=agora + VALIDADE_DO_QUADRO,
        )

    def _clausulas(
        self,
        e: ConsultaEntendida,
        nome: Callable[[str | None], str | None],
    ) -> list[_Clausula]:
        base = _base(e)
        clausulas: list[_Clausula] = []
        donos: set[str] = set()
        for o in e.objetos:
            # O índice não aceita cláusula só de filtros: a peça vai também como texto.
            texto = o.tipo or o.cor_base or o.categoria
            if not texto:
                continue
            if o.dono:
                donos.add(o.dono)
            clausulas.append(
                _Clausula(
                    Consulta(
                        filtros=replace(
                            base,
                            tipo="objeto",
                            categoria=o.categoria,
                            cor_base=o.cor_base,
                            dono=o.dono,
                        ),
                        texto=texto,
                    ),
                    lambda r: _motivo(r, nome),
                )
            )
        for marca in e.marcas:
            clausulas.append(
                _Clausula(
                    Consulta(
                        filtros=replace(base, tipo="objeto", marca=marca), texto=marca
                    ),
                    lambda r: _motivo(r, nome),
                )
            )
        for pessoa in e.pessoas:
            if pessoa in donos:
                continue
            clausulas.extend(_clausulas_da_pessoa(pessoa, e, base, nome))
        if e.frase_exata:
            for tipo in _tipos_de_texto(e):
                clausulas.append(
                    _Clausula(
                        Consulta(filtros=replace(base, tipo=tipo), texto=e.frase_exata),
                        lambda r: _motivo(r, nome),
                    )
                )
        if e.texto_livre:
            clausulas.append(
                _Clausula(
                    Consulta(
                        filtros=base,
                        texto=e.texto_livre,
                        significado=e.texto_livre,
                        cortar_significado=True,
                    ),
                    lambda r: _motivo(r, nome),
                )
            )
        return clausulas

    def _videos(
        self,
        trechos: list[_Trecho],
        job: Callable[[str], Job | None],
        termos: list[str],
        ordem: Ordem,
    ) -> list[VideoDoResultado]:
        por_video: dict[str, list[_Trecho]] = defaultdict(list)
        for t in trechos:
            por_video[t.job_id].append(t)
        videos: list[tuple[int, VideoDoResultado]] = []
        for id, lista in por_video.items():
            j = job(id)
            if j is None:
                continue
            # A relevância também dentro do vídeo; no empate, o tempo.
            lista.sort(key=lambda t: (t.posicao, t.inicio_ms, t.fim_ms))
            momentos = [
                Momento(
                    inicio_ms=t.inicio_ms,
                    fim_ms=t.fim_ms,
                    motivo=t.motivo,
                    destaques=_destaques(t.motivo, termos),
                    quadro_url=(
                        self._armazenamento.url_do_quadro(
                            id, t.quadro, VALIDADE_DO_QUADRO
                        )
                        if t.quadro
                        else None
                    ),
                )
                for t in lista
            ]
            videos.append(
                (
                    min(t.posicao for t in lista),
                    VideoDoResultado(
                        job_id=id,
                        nome=j.nome,
                        programa=j.programa,
                        data_exibicao=j.data_exibicao,
                        duracao_s=j.duracao_s,
                        n_momentos=len(momentos),
                        momentos=momentos,
                    ),
                )
            )
        videos.sort(key=lambda v: (v[0], -v[1].n_momentos))
        if ordem == "data":
            # Estável: na mesma data, fica a relevância; sem data, no fim.
            videos.sort(key=lambda v: v[1].data_exibicao or date.min, reverse=True)
        return [v for _, v in videos]

    def _sem_aparicao(
        self,
        pessoa: str,
        e: ConsultaEntendida,
        consultar: Callable[[Consulta], list[Registro]],
        nome: Callable[[str | None], str | None],
    ) -> SemAparicao:
        """Quantas vezes a pessoa sem aparição é citada, no mesmo programa e período."""
        quem = nome(pessoa) or ""
        base = _base(e)
        na_fala = consultar(Consulta(filtros=replace(base, tipo="fala"), texto=quem))
        na_tela = consultar(
            Consulta(filtros=replace(base, tipo="texto_na_tela"), texto=quem)
        )
        return SemAparicao(
            pessoa_id=pessoa,
            nome=quem,
            mencoes_na_fala=len(na_fala),
            mencoes_na_tela=len(na_tela),
        )


def _casa(r: Registro, a: Ajustes) -> bool:
    """O registro passa nas facetas de pessoa, marca e tipo que o editor clicou."""
    return (
        (a.pessoa is None or a.pessoa in r.pessoas or a.pessoa == r.dono)
        and (a.marca is None or r.marca == a.marca)
        and (a.tipo is None or r.tipo == a.tipo)
    )


def _com_facetas(c: Consulta, a: Ajustes) -> list[Consulta]:
    """A consulta da cláusula com as facetas no filtro; nenhuma, se elas se excluem.

    A pessoa casa na imagem (`pessoa`, que o objeto não tem) ou como dona do objeto
    (`dono`): sem tipo na cláusula, isso dá duas consultas.
    """
    f = c.filtros
    if a.tipo is not None:
        if f.tipo not in (None, a.tipo):
            return []
        f = replace(f, tipo=a.tipo)
    if a.marca is not None:
        if f.marca not in (None, a.marca):
            return []
        f = replace(f, marca=a.marca)
    if a.pessoa is None:
        return [replace(c, filtros=f)]
    filtros: list[Filtros] = []
    if f.tipo in (None, "objeto") and f.dono in (None, a.pessoa):
        filtros.append(replace(f, tipo="objeto", dono=a.pessoa))
    # Marca só existe no objeto; outra pessoa já filtrada fica para o `_casa`.
    if f.tipo != "objeto" and f.marca is None:
        filtros.append(
            f if f.pessoa not in (None, a.pessoa) else replace(f, pessoa=a.pessoa)
        )
    return [replace(c, filtros=x) for x in filtros]


def _intercalar(listas: list[list[Registro]]) -> list[Registro]:
    """Uma lista só, alternando as posições, para nenhuma consulta passar na frente."""
    return [r for grupo in zip_longest(*listas) for r in grupo if r is not None]


def _facetas(
    candidatos: list[Registro],
    nome: Callable[[str | None], str | None],
) -> Facetas:
    """Vídeos distintos por valor, sobre os candidatos (os registros que sobraram do RRF).

    ponytail: o Agent Retrieval não devolve contagem por faceta (a API só traz os registros
    e o índice não agrega), então a conta é nossa e vai até `TETO_DE_REGISTROS` (100)
    candidatos fundidos (cada cláusula traz até 100, já com os filtros e as facetas no
    índice): o valor que só aparece além deles não entra, e as contagens são de
    "vídeos entre os 100 melhores registros", não do acervo todo.
    """
    por_faceta: dict[str, dict[str, tuple[str, set[str]]]] = {
        f: {} for f in ("programa", "mes", "pessoa", "marca", "tipo")
    }

    def contar(faceta: str, valor: str | None, rotulo: str | None, id: str) -> None:
        if valor:
            por_faceta[faceta].setdefault(valor, (rotulo or valor, set()))[1].add(id)

    # Programa e mês vêm do registro, que é o que o filtro compara (não do Job).
    for r in candidatos:
        contar("programa", r.programa, None, r.job_id)
        if r.data_de_exibicao:
            mes = r.data_de_exibicao
            contar("mes", mes.strftime("%Y-%m"), mes.strftime("%m/%Y"), r.job_id)
        for pessoa in dict.fromkeys([*r.pessoas, *([r.dono] if r.dono else [])]):
            contar("pessoa", pessoa, nome(pessoa), r.job_id)
        contar("marca", r.marca, None, r.job_id)
        contar("tipo", r.tipo, ROTULO_DO_TIPO.get(r.tipo), r.job_id)

    def valores(faceta: str, por_mes: bool = False) -> list[ValorDaFaceta]:
        lista = [
            ValorDaFaceta(valor=v, rotulo=rotulo, videos=len(ids))
            for v, (rotulo, ids) in por_faceta[faceta].items()
            # Pessoa que o catálogo não conhece não tem o que mostrar.
            if faceta != "pessoa" or rotulo != v
        ]
        lista.sort(key=lambda x: (-x.videos, x.rotulo))
        lista = lista[:TETO_DE_VALORES_POR_FACETA]
        if por_mes:
            lista.sort(key=lambda x: x.valor, reverse=True)
        return lista

    return Facetas(
        programa=valores("programa"),
        mes=valores("mes", por_mes=True),
        pessoa=valores("pessoa"),
        marca=valores("marca"),
        tipo=valores("tipo"),
    )


def _ligadas(e: ConsultaEntendida) -> list[EvidenciaDaBusca]:
    """Os chips ligados: as evidências da consulta (ou o padrão de pessoa e de frase)."""
    ligadas: list[EvidenciaDaBusca] = list(e.evidencias)
    if not ligadas and e.pessoas:
        ligadas.append("imagem")
    if not ligadas and e.frase_exata:
        ligadas.append("fala")
    if e.objetos:
        ligadas.append("objeto")
    if e.marcas:
        ligadas.append("marca")
    return ligadas


def _ajustada(e: ConsultaEntendida, a: Ajustes) -> ConsultaEntendida:
    """Aplica o que o editor ligou ou desligou; só o que ele pediu muda."""
    if a.evidencias:
        ligadas = set(a.evidencias)
        do_modelo = tuple(x for x in EVIDENCIAS if x in ligadas)
        e = replace(
            e,
            evidencias=do_modelo,
            objetos=e.objetos if "objeto" in ligadas else (),
            marcas=e.marcas if "marca" in ligadas else (),
            # Sem evidência de pessoa ou de frase ligada, as duas saem (o padrão ligaria uma).
            pessoas=e.pessoas if do_modelo else (),
            frase_exata=e.frase_exata if do_modelo else None,
        )
    if a.programa is not None:
        e = replace(e, programa=a.programa or None)
    if a.sem_periodo:
        e = replace(e, exibido_desde=None, exibido_ate=None)
    if a.desde is not None:
        e = replace(e, exibido_desde=a.desde)
    if a.ate is not None:
        e = replace(e, exibido_ate=a.ate)
    return e


def _base(e: ConsultaEntendida) -> Filtros:
    """Os filtros que a consulta impõe a toda cláusula: programa e período."""
    return Filtros(
        programa=e.programa,
        exibido_desde=e.exibido_desde,
        exibido_ate=e.exibido_ate,
    )


def _evidencias(e: ConsultaEntendida) -> tuple[str, ...]:
    return e.evidencias or ("imagem",)


def _tipos_de_texto(e: ConsultaEntendida) -> list[Literal["fala", "texto_na_tela"]]:
    """A frase exata vale na fala, salvo se o usuário pediu só o que está escrito na tela."""
    evidencias = e.evidencias or ("fala",)
    tipos: list[Literal["fala", "texto_na_tela"]] = []
    if "fala" in evidencias or "citada" in evidencias:
        tipos.append("fala")
    if "gc" in evidencias or "citada" in evidencias:
        tipos.append("texto_na_tela")
    return tipos or ["fala"]


def _clausulas_da_pessoa(
    pessoa: str,
    e: ConsultaEntendida,
    base: Filtros,
    nome: Callable[[str | None], str | None],
) -> list[_Clausula]:
    quem = nome(pessoa)
    clausulas: list[_Clausula] = []
    evidencias = _evidencias(e)
    if "imagem" in evidencias and quem:
        # O índice não aceita cláusula só de filtros: os planos dela vão pelo significado.
        clausulas.append(
            _Clausula(
                Consulta(
                    filtros=replace(base, tipo="plano", pessoa=pessoa),
                    significado=e.texto_livre or quem,
                ),
                lambda r: f"Na imagem: {quem}",
                pessoa_na_imagem=pessoa,
            )
        )
    if quem:
        if "fala" in evidencias or "citada" in evidencias:
            clausulas.append(
                _Clausula(
                    Consulta(filtros=replace(base, tipo="fala"), texto=quem),
                    lambda r: _motivo(r, nome),
                )
            )
        if "gc" in evidencias or "citada" in evidencias:
            clausulas.append(
                _Clausula(
                    Consulta(filtros=replace(base, tipo="texto_na_tela"), texto=quem),
                    lambda r: _motivo(r, nome),
                )
            )
    return clausulas


def _motivo(r: Registro, nome: Callable[[str | None], str | None]) -> str:
    """O motivo em palavras; o texto vem do índice e segue como texto puro."""
    if r.tipo == "objeto":
        peca = " ".join(
            p
            for p in (r.tipo_do_objeto or r.categoria, r.cor or " ".join(r.cor_base))
            if p
        )
        dono = nome(r.dono)
        return f"Objeto: {peca} · {dono}" if dono else f"Objeto: {peca}"
    if r.tipo == "fala":
        return f"Fala: '{r.texto}'"
    if r.tipo == "texto_na_tela":
        return f"GC: {r.texto}"
    return f"Plano: {r.descricao}" if r.descricao else "Plano"


def _termos(
    e: ConsultaEntendida, nome: Callable[[str | None], str | None]
) -> list[str]:
    """O que se destaca no motivo: a frase, o texto livre e o nome das pessoas citadas."""
    termos = [e.frase_exata] if e.frase_exata else []
    if e.texto_livre:
        # Palavras de uma ou duas letras ("de", "da") acenderiam dentro de outras.
        termos += [
            e.texto_livre,
            *(p for p in normalizar(e.texto_livre).split() if len(p) > 2),
        ]
    termos += [q for p in e.pessoas if (q := nome(p))]
    return termos


def _peso(r: Registro) -> float:
    return 1 + PESO_POR_NIVEL_DE_DESTAQUE * max((r.destaque or 1) - 1, 0)


def _fundir(listas: list[list[Registro]]) -> list[tuple[Registro, int, float]]:
    """RRF entre as cláusulas; cada registro leva a cláusula em que ficou melhor e os pontos."""
    pontos: dict[str, float] = defaultdict(float)
    melhor: dict[str, tuple[int, int]] = {}  # id -> (posição, cláusula)
    registros: dict[str, Registro] = {}
    for c, lista in enumerate(listas):
        for posicao, r in enumerate(lista):
            pontos[r.id] += _peso(r) / (RRF_K + posicao + 1)
            registros[r.id] = r
            if r.id not in melhor or posicao < melhor[r.id][0]:
                melhor[r.id] = (posicao, c)
    ids = sorted(pontos, key=lambda i: (-pontos[i], melhor[i]))
    return [(registros[i], melhor[i][1], pontos[i]) for i in ids[:TETO_DE_REGISTROS]]


def _posicoes_por_pontos(fundidos: list[tuple[Registro, int, float]]) -> dict[str, int]:
    """A posição de cada registro pela pontuação; mesma pontuação, mesma posição."""
    niveis = sorted({round(p, 12) for _, _, p in fundidos}, reverse=True)
    nivel = {p: i for i, p in enumerate(niveis)}
    return {r.id: nivel[round(p, 12)] for r, _, p in fundidos}


def _juntar(
    registros: list[Registro], motivos: dict[str, str], posicao: dict[str, int]
) -> list[_Trecho]:
    """Registros do mesmo vídeo, com o mesmo motivo e a até 3 s um do outro, viram um trecho."""
    trechos: list[_Trecho] = []
    abertos: dict[tuple[str, str], _Trecho] = {}
    for r in sorted(registros, key=lambda r: (r.job_id, r.inicio_ms, r.fim_ms)):
        chave = (r.job_id, motivos[r.id])
        atual = abertos.get(chave)
        if atual and r.inicio_ms - atual.fim_ms <= JUNCAO_MS:
            atual.fim_ms = max(atual.fim_ms, r.fim_ms)
            atual.posicao = min(atual.posicao, posicao[r.id])
            atual.quadro = atual.quadro or r.quadro
            continue
        atual = _Trecho(
            r.job_id, r.inicio_ms, r.fim_ms, motivos[r.id], posicao[r.id], r.quadro
        )
        abertos[chave] = atual
        trechos.append(atual)
    return trechos
