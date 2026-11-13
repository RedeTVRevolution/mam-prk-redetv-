"""Busca (#120): o texto saneado vira cláusulas no índice, que voltam fundidas por RRF,
reordenadas, juntadas em trechos e agrupadas por vídeo.

Os filtros do servidor (permissão, lixeira) entram por cima de tudo o que vem da consulta
(`com_filtros_do_servidor`); nomes de campo e operadores são fixos no código, e o texto
do usuário só chega ao índice como texto puro.
"""

import hashlib
import json
import logging
import re
import secrets
import threading
import time
import unicodedata
import zlib
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, fields, replace
from datetime import date, datetime, timedelta
from itertools import zip_longest
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, PrivateAttr

from api.cache_curto import CacheCurto
from api.catalogo import Catalogo, CopiaCurta, PessoaDoCatalogo
from api.comparador import normalizar
from api.entendimento_da_consulta import (
    ConsultaEntendida,
    IndiceDeNomesCitados,
    entender,
    termo_da_foto,
)
from api.gemini import ErroHttp, Transporte
from api.indice_da_busca import (
    Consulta,
    Filtros,
    IndiceDaBusca,
    Registro,
    TipoDeRegistro,
)
from api.jobs import (
    VALIDADE_DA_IMAGEM,
    VALIDADE_INFORMADA_DA_IMAGEM,
    Armazenamento,
    CursorInvalido,
    Job,
    RepositorioDeJobs,
)
from api.lixeira_na_leitura import (
    PurgasDeMarca,
    PurgasDeMarcaEmMemoria,
    VersaoDaLixeira,
    VersaoDaLixeiraEmMemoria,
    conta_depois_do_corte,
    cortes_validos,
    lido,
    nomes_de_marca_na_lixeira,
    pessoas_que_contam,
)
from api.marcas import CatalogoDeMarcas, CatalogoDeMarcasEmMemoria
from api.numero import com_as_formas, mesma_palavra, singular

log = logging.getLogger(__name__)

RRF_K = 60
# Cada nível de destaque acima de 1 soma isto à pontuação do objeto do inventário: o
# destaque 3 (+6%) passa quem está logo atrás, uns três lugares no topo da lista (a
# pontuação é 1/(60+posição), então o ganho cresce para uns nove lugares na
# centésima posição), e não quem está bem mais acima. Registro sem destaque pesa 1.
PESO_POR_NIVEL_DE_DESTAQUE = 0.03
# Por cláusula e depois da fusão. A 1ª página junta o resultado inteiro (até uns 500
# vídeos), que as páginas seguintes leem do Firestore sem refazer a busca (#426).
TETO_DE_REGISTROS = 500
# A Ranking API cobra pelos registros enviados ("ranking units are computed from the number
# of records sent to the ranker and the size of their title and content templates"): com
# 500 candidatos, ela custaria proporcionalmente mais que antes. Só os 100 primeiros da fusão são
# reordenados, o mesmo volume de quando o teto era 100; o resto vem depois deles, na
# ordem do índice, e é o que a pessoa só vê a partir da 2ª ou 3ª página.
TETO_DO_RANKING = 100
# Quanto vale o cursor da busca: o Firestore apaga a lista depois (política de TTL).
VALIDADE_DA_LISTA = timedelta(minutes=15)
# O campo comprimido da lista, bem abaixo do 1 MiB do documento do Firestore.
TETO_DA_LISTA_BYTES = 800_000
TETO_DE_VIDEOS = 50
VIDEOS_POR_PADRAO = 20
JUNCAO_MS = 3_000
# Assinaturas simultâneas para a chave de sistema: cada uma é uma ida ao IAM, e cem
# momentos em fila passavam dos 15 s da rota.
TETO_DE_ASSINATURAS = 16
# Consultas ao índice simultâneas numa busca. A espera é de rede (as threads soltam o GIL),
# então o teto cobre as consultas de uma busca típica (pessoa com 4 cláusulas; #568); busca
# com mais que isso espera uma rodada. `pool.map` entrega na ordem das consultas.
TETO_DE_CONSULTAS_AO_INDICE = 8
# Quanto a mesma busca reaproveita os candidatos do índice e a ordem do ranking (#568). Um
# minuto cobre quem volta, reordena ou repete a busca; vídeo indexado dentro dele só
# aparece quando o cache vence. Os Jobs (sistema, estado, lixeira) são relidos a cada busca.
VALIDADE_DOS_CANDIDATOS_S = 60.0
# Até uns 500 registros por entrada: poucas entradas, para a memória da instância.
MAXIMO_DE_CANDIDATOS = 48
# Valores mostrados por faceta: os de mais vídeos.
TETO_DE_VALORES_POR_FACETA = 20
ROTULO_DO_TIPO: dict[str, str] = {
    "plano": "Plano",
    "fala": "Fala",
    "texto_na_tela": "GC",
    "objeto": "Objeto",
}

Ordem = Literal["relevancia", "data"]
# As evidências que o editor liga e desliga na tela.
EvidenciaDaBusca = Literal["imagem", "citada", "fala", "gc", "objeto", "marca"]


class BuscaCancelada(Exception):
    """A rota desistiu (passou do prazo): o trabalho que sobra para em vez de seguir rodando."""


class BuscaPorImagemIndisponivel(Exception):
    """O modelo da consulta está fora ou não achou objeto na foto: a imagem não vira termo."""


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
    tipo: TipoDeRegistro  # o tipo do registro: plano, objeto, pessoa...
    inicio_ms: int
    fim_ms: int
    motivo: str
    destaques: list[Destaque]
    # Assinada só para chave de sistema; a web recebe `null`. Obsoleto: sairá da resposta,
    # os sistemas pedem a URL pela rota do quadro a partir do campo `quadro`.
    quadro_url: str | None = Field(
        json_schema_extra={
            "deprecated": True
        },  # só no esquema: `deprecated=True` avisa a cada leitura
        description=(
            "Obsoleto: vai sair da resposta. Use o campo `quadro` e peça a URL em "
            "`GET /v1/jobs/{job_id}/quadros/{arquivo}`, com o nome do arquivo do "
            "`quadro` (`plano-6.jpg`)."
        ),
    )
    # Caminho do quadro no vídeo (`quadros/plano-6.jpg`): a web pede a URL pela rota do quadro.
    quadro: str | None = None


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

    pessoa_id: str | None  # `None`: o nome que o catálogo não resolve
    nome: str
    mencoes_na_fala: int
    mencoes_na_tela: int


class Entendida(BaseModel):
    """Filtros aplicados e termo da foto; o nome do campo fica por compatibilidade."""

    evidencias: list[EvidenciaDaBusca]
    programa: str | None
    desde: date | None
    ate: date | None
    # Só na busca por foto (#443): o termo que o modelo deu para o objeto e que a busca usou,
    # como se tivesse sido digitado. A tela o mostra para a pessoa poder refinar digitando.
    termo_da_foto: str | None = None


@dataclass(frozen=True)
class Ajustes:
    """Os filtros que o editor escolheu na tela."""

    evidencias: tuple[EvidenciaDaBusca, ...] = ()  # vazio: todos os tipos
    programa: str | None = None  # "": sem programa
    desde: date | None = None
    ate: date | None = None
    sem_periodo: bool = False  # o "Todos os anos" da tela
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
    # A página seguinte (#426): a rota a põe no cabeçalho `X-Proximo-Cursor`, fora do corpo.
    _proximo_cursor: str | None = PrivateAttr(default=None)


class MomentoGuardado(BaseModel):
    """O momento como fica na lista: os destaques e a URL são refeitos a cada página."""

    tipo: TipoDeRegistro
    inicio_ms: int
    fim_ms: int
    motivo: str
    quadro: str | None


class VideoGuardado(BaseModel):
    """Nome, programa e data vêm do Job, relido a cada página."""

    job_id: str
    momentos: list[MomentoGuardado]


# Os campos que o documento guarda soltos; o resto vai num campo só, comprimido.
_SOLTOS = {"dono", "impressao", "criado_em", "expira_em"}


class ListaDaBusca(BaseModel):
    """O resultado inteiro, em ordem, guardado na 1ª página para as seguintes (#426)."""

    dono: str  # o uid, ou `sistema:<nome>` da chave
    impressao: str  # SHA-256 da consulta e dos filtros
    criado_em: datetime
    expira_em: datetime  # o campo da política de TTL
    entendida: Entendida
    sem_aparicoes: list[SemAparicao]
    plano_b: bool
    facetas: Facetas
    termos: list[str]
    videos: list[VideoGuardado]
    # A versão da lixeira do catálogo lida antes da 1ª decisão (#598); `None` é o formato
    # antigo, de antes dela: a página seguinte o recusa.
    versao_da_lixeira: int | None = None

    def para_documento(self) -> dict[str, Any]:
        """A lista num campo de bytes: o Firestore não indexa item por item, e o
        tamanho medido é o que vai ao documento."""
        resto = self.model_dump_json(exclude=_SOLTOS).encode()
        return {k: getattr(self, k) for k in _SOLTOS} | {
            "conteudo": zlib.compress(resto)
        }

    @classmethod
    def do_documento(cls, documento: Mapping[str, Any]) -> "ListaDaBusca":
        resto = json.loads(zlib.decompress(documento["conteudo"]))
        return cls.model_validate({k: documento[k] for k in _SOLTOS} | resto)


class ListasDaBusca(Protocol):
    """Porta para o Firestore, com o documento de `ListaDaBusca.para_documento` (o
    adaptador não importa a busca: as imagens de GPU o copiam sem ela)."""

    def gravar(self, documento: dict[str, Any]) -> str:
        """Grava com um id aleatório, só de letras e números, e o devolve."""
        ...

    def ler(self, id: str) -> dict[str, Any] | None: ...


class ListasDaBuscaEmMemoria:
    def __init__(self) -> None:
        self.documentos: dict[str, dict[str, Any]] = {}

    def gravar(self, documento: dict[str, Any]) -> str:
        id = secrets.token_hex(10)
        self.documentos[id] = documento
        return id

    def ler(self, id: str) -> dict[str, Any] | None:
        return self.documentos.get(id)


def filtros_do_servidor() -> Filtros:
    """Os filtros que o servidor impõe a toda busca, acima da consulta.

    O vídeo na lixeira (#144) fica fora do índice por `na_lixeira=False`, para não ocupar o
    teto de registros (#483); a regra de verdade segue no Job: `Busca` descarta o vídeo cujo
    Job não está concluído ou está na lixeira, e o de outro sistema.
    """
    return Filtros(na_lixeira=False)


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
    for original in {t for t in termos if len(t.strip()) >= 2}:
        termo = _sem_acento(original)
        i = palheiro.find(termo)
        while i != -1:
            achados.append((i, i + len(termo)))
            i = palheiro.find(termo, i + len(termo))
        # A mesma palavra no outro número ("microfone" × "microfones", "avião" × "aviões").
        if " " not in original.strip():
            for achado in re.finditer(r"\w+", texto):
                if mesma_palavra(achado.group(), original):
                    achados.append((achado.start(), achado.end()))
    unidos: list[list[int]] = []
    for inicio, fim in sorted(achados):
        if unidos and inicio <= unidos[-1][1]:
            unidos[-1][1] = max(unidos[-1][1], fim)
        else:
            unidos.append([inicio, fim])
    return [Destaque(inicio=i, fim=f) for i, f in unidos]


def _conferir(cancelado: threading.Event | None) -> None:
    if cancelado is not None and cancelado.is_set():
        raise BuscaCancelada


@dataclass
class _Trecho:
    job_id: str
    inicio_ms: int
    fim_ms: int
    motivo: str
    posicao: int  # a melhor posição, no resultado fundido, entre os registros juntados
    quadro: str | None
    tipo: TipoDeRegistro


_agora = time.perf_counter  # troca-se nos testes por um relógio controlado


class Busca:
    def __init__(
        self,
        *,
        transporte: Transporte,
        catalogo: Catalogo,
        indice: IndiceDaBusca,
        ranking: Ranking,
        repositorio: RepositorioDeJobs,
        armazenamento: Armazenamento,
        relogio: Callable[[], datetime],
        copia_do_catalogo: CopiaCurta[PessoaDoCatalogo] | None = None,
        listas: ListasDaBusca | None = None,
        cache_de_candidatos: CacheCurto | None = None,
        versao_da_lixeira: VersaoDaLixeira | None = None,
        marcas: CatalogoDeMarcas | None = None,
        purgas: PurgasDeMarca | None = None,
    ) -> None:
        self._marcas = marcas or CatalogoDeMarcasEmMemoria()
        self._purgas = purgas or PurgasDeMarcaEmMemoria()
        self._versao = versao_da_lixeira or VersaoDaLixeiraEmMemoria()
        self._listas = listas or ListasDaBuscaEmMemoria()
        self._candidatos = cache_de_candidatos or CacheCurto(
            validade=VALIDADE_DOS_CANDIDATOS_S, maximo=MAXIMO_DE_CANDIDATOS
        )
        # A mesma cópia do autocompletar, se a aplicação a passa: uma só recarga para todos.
        self._nomes_citados = IndiceDeNomesCitados()
        self._copia_do_catalogo = copia_do_catalogo or CopiaCurta(
            catalogo.todas, relogio
        )
        self._transporte = transporte
        self._catalogo = catalogo
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
        imagem: bytes | None = None,
        cancelado: threading.Event | None = None,
        cursor: str | None = None,
        dono: str = "",
    ) -> ResultadoDaBusca:
        """Sem `cursor`, faz a busca e, se sobra vídeo além de `limite`, guarda a lista
        inteira para `dono` (#426); com o `_proximo_cursor` de uma página, só lê a lista
        e corta a página, sem modelo, índice nem ranking (`CursorInvalido` se a lista não
        existe, venceu, é de outro dono ou de outra consulta).

        `imagem` (JPEG já regravado, #270): o modelo da consulta dá o termo do objeto da
        foto (#443) e a busca segue como se a pessoa o tivesse digitado, com o mesmo
        saneamento, índice e ranking; só os filtros de `ajustes` valem. Sem o modelo,
        se ele falhar ou não achar objeto, levanta `BuscaPorImagemIndisponivel`: sem texto
        digitado não há plano B."""
        inicio = _agora()
        impostos = filtros_do_servidor or Filtros()
        if sistema is not None:
            # O filtro do índice só tira inelegíveis do teto; `_visivel_de` decide.
            impostos = replace(impostos, sistema=sistema)
        termo_da_foto = None
        impressao = _impressao(
            texto=texto,
            ordem=ordem,
            imagem=hashlib.sha256(imagem).hexdigest() if imagem is not None else None,
            sistema=sistema,
            ajustes=asdict(ajustes or Ajustes()),
            filtros=asdict(impostos),
        )
        if cursor is not None:
            return self._pagina_seguinte(
                cursor, limite, dono, impressao, sistema, cancelado
            )
        # Lida antes de qualquer decisão sobre quem conta e gravada na lista: uma mudança na
        # lixeira do catálogo no meio da busca faz a página seguinte ser recusada (#598).
        versao = self._versao.atual()
        if imagem is not None:
            _conferir(cancelado)
            texto = termo_da_foto = self._termo_da_foto(imagem)
        entendida = _ajustada(
            entender(
                texto,
                catalogo=self._catalogo,
                todas=self._copia_do_catalogo.itens,
                indice=self._nomes_citados,
            ),
            ajustes or Ajustes(),
        )
        jobs: dict[str, Job | None] = {}

        def carregar_jobs(ids: Iterable[str]) -> None:
            """Lê numa leitura em lote os Jobs ainda não lidos."""
            faltam = list(dict.fromkeys(i for i in ids if i not in jobs))
            if not faltam:
                return
            lidos = {
                j.id: j for j in lido(lambda: self._repositorio.obter_varios(faltam))
            }
            for i in faltam:
                jobs[i] = self._visivel_de(lidos.get(i), sistema)

        def job(id: str) -> Job | None:
            carregar_jobs([id])
            return jobs[id]

        def do_indice(c: Consulta) -> list[Registro]:
            _conferir(cancelado)
            c = replace(
                c,
                filtros=com_filtros_do_servidor(c.filtros, impostos),
                limite=TETO_DE_REGISTROS,
            )
            # O cache guarda a lista do índice; cada busca recebe cópias, porque os
            # registros levam listas que ninguém de fora pode compartilhar.
            return [
                replace(r, pessoas=list(r.pessoas), cor_base=list(r.cor_base))
                for r in self._candidatos.obter(
                    ("indice", impressao, c), lambda: self._indice.buscar(c)
                )
            ]

        prontas: list[tuple[Consulta, list[Registro]]] = []

        def consultar(c: Consulta) -> list[Registro]:
            """Só na thread da busca: o dicionário de Jobs não é escrito por mais de uma."""
            achados = next((a for q, a in prontas if q == c), None)
            if achados is None:
                achados = sem_excluidas(c, do_indice(c))
            carregar_jobs(r.job_id for r in achados)
            return [r for r in achados if job(r.job_id)]

        nomes: dict[str, str] = {}

        def carregar_nomes(ids: Iterable[str | None]) -> None:
            """Lê numa leitura em lote os nomes ainda não lidos; sem pessoa vale `""`."""
            faltam = list(dict.fromkeys(i for i in ids if i and i not in nomes))
            if not faltam:
                return
            lidas = self._catalogo.obter_varios(faltam)
            for i in faltam:
                nomes[i] = lidas[i].nome if i in lidas else ""

        def nome(id: str | None) -> str | None:
            carregar_nomes([id])
            return nomes.get(id or "") or None

        # A lixeira do catálogo vale na leitura (#583): só conta quem existe no catálogo, fora
        # da lixeira. O estado é lido em lote, uma vez por id, e vale para toda a busca.
        contam: set[str] = set()
        decididos: set[str] = set()
        # A marca na lixeira (#594): uma leitura por busca, depois da versão.
        sem_marca = nomes_de_marca_na_lixeira(self._marcas)

        # Uma mudança na lixeira no meio da busca mistura dois estados do catálogo nesta 1ª
        # página (consulta decidida antes do índice, registros depois); a `versao` do início
        # faz a página seguinte ser recusada.
        def decidir(ids: Iterable[str | None]) -> None:
            faltam = {i for i in ids if i and i not in decididos}
            if faltam:
                decididos.update(faltam)
                contam.update(pessoas_que_contam(self._catalogo, faltam))

        # A marca purgada (#599) corta por candidato, pelo `criado_em` do Job dele: o registro
        # das purgas é lido uma vez por busca, junto do estado da lixeira.
        purgadas = lido(self._purgas.todas)
        cortes: dict[str, datetime] = {}
        marcas_vistas: set[str] = set()

        def sem_marca_purgada(achados: list[Registro]) -> list[Registro]:
            """Tira a `marca` do registro de Job criado até a purga dela (Job ausente conta
            como anterior); os Jobs dos candidatos com marca cortada são lidos aqui."""
            novas = {normalizar(r.marca) for r in achados if r.marca} - marcas_vistas
            if novas:
                marcas_vistas.update(novas)
                cortes.update(cortes_validos(purgadas, self._marcas, novas))
            carregar_jobs(
                r.job_id for r in achados if r.marca and normalizar(r.marca) in cortes
            )

            def sai(r: Registro) -> bool:
                corte = cortes.get(normalizar(r.marca)) if r.marca else None
                if corte is None:
                    return False
                dele = jobs[r.job_id]
                return not conta_depois_do_corte(
                    dele.criado_em if dele else None, corte
                )

            return [replace(r, marca=None) if sai(r) else r for r in achados]

        def sem_excluidas(c: Consulta, achados: list[Registro]) -> list[Registro]:
            """Tira de `pessoas`, `dono` e `marca` quem não conta e confere o registro de novo
            contra os filtros de pessoa, dono e marca da consulta (cláusula e tela): fica só se
            ainda casa. O texto do registro não muda."""
            decidir(p for r in achados for p in (*r.pessoas, r.dono))
            achados = sem_marca_purgada(achados)
            limpos = [_sem_quem_nao_conta(r, contam, sem_marca) for r in achados]
            return [r for r in limpos if _ainda_casa(r, c.filtros)]

        decidir(entendida.pessoas)
        carregar_nomes(entendida.pessoas)
        clausulas = self._clausulas(entendida, nome, contam)
        t_entender = _agora() - inicio
        facetado = ajustes or Ajustes()
        # As facetas vão ao índice, para não filtrar só o que coube no teto de registros;
        # o `_casa` confere o que o índice não exprime (duas pessoas na mesma cláusula).
        # Os Jobs de todas as cláusulas, e depois os nomes dos registros, vêm em lote.
        # As consultas vão ao índice juntas, no máximo `TETO_DE_CONSULTAS_AO_INDICE` de cada
        # vez; cada uma segue com a sua fusão (RRF), e a ordem de antes é a dos resultados.
        # Se uma falha, o erro sobe sem esperar as que ainda nem saíram.
        por_clausula = [_com_facetas(c.consulta, facetado) for c in clausulas]
        planas = [q for qs in por_clausula for q in qs]
        # Sem `with`: a saída do bloco esperaria as consultas presas; o limite de cada uma
        # é o prazo da leitura do índice (15 s, `transporte_http`).
        pool = ThreadPoolExecutor(
            max_workers=max(1, min(TETO_DE_CONSULTAS_AO_INDICE, len(planas)))
        )
        try:
            achados_do_indice = list(pool.map(do_indice, planas))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        # Depois do cache e antes da fusão (RRF), do corte do ranking e dos vídeos. Em lote
        # de propósito: uma leitura do catálogo para todas as consultas, não uma por consulta.
        decidir(p for a in achados_do_indice for r in a for p in (*r.pessoas, r.dono))
        entregues = iter(
            [
                sem_excluidas(q, a)
                for q, a in zip(planas, achados_do_indice, strict=True)
            ]
        )
        t_indice = _agora() - inicio
        brutos = [[next(entregues) for _ in qs] for qs in por_clausula]
        prontas.extend(zip(planas, (l for da in brutos for l in da), strict=True))
        carregar_jobs(
            r.job_id for da_clausula in brutos for lista in da_clausula for r in lista
        )
        t_jobs = _agora() - inicio
        resultados = [
            [
                r
                for r in _intercalar(
                    [[r for r in lista if job(r.job_id)] for lista in da_clausula]
                )
                if _casa(r, facetado) and _tem_a_frase(r, entendida.frase_exata)
            ]
            for da_clausula in brutos
        ]
        carregar_nomes(
            p
            for da_clausula in resultados
            for r in da_clausula
            for p in (*r.pessoas, r.dono)
        )
        t_nomes = _agora() - inicio
        sem_facetas = all(
            x is None for x in (facetado.pessoa, facetado.marca, facetado.tipo)
        )
        fundidos = _fundir(resultados)
        achados = [r for r, _, _ in fundidos]
        # Sem a API de Ranking, a posição é a da pontuação do RRF: registros de mesma
        # pontuação empatam, e o desempate dos vídeos é o número de momentos.
        posicao = _posicoes_por_pontos(fundidos)
        t_fusao = _agora() - inicio
        if _texto_da_busca(entendida) and achados:
            try:
                achados = [
                    *self._reordenar(
                        impressao, _texto_da_busca(entendida), achados[:TETO_DO_RANKING]
                    ),
                    *achados[TETO_DO_RANKING:],
                ]
                # A ordem do ranking, com o peso do destaque sobre a posição. O resto, que
                # não foi ao ranking, fica sempre depois, na ordem do índice: pontos
                # negativos, sem o peso, para nenhum destaque passar à frente dos 100.
                posicao = _posicoes_por_pontos(
                    [
                        (
                            r,
                            0,
                            _peso(r) / (RRF_K + i + 1) if i < TETO_DO_RANKING else -i,
                        )
                        for i, r in enumerate(achados)
                    ]
                )
            except Exception:
                log.exception("ranking indisponível; fica a ordem do índice")
        t_ranking = _agora() - inicio
        _conferir(cancelado)
        motivo_de = {r.id: clausulas[c].motivo(r) for r, c, _ in fundidos}
        termos = _termos(entendida, nome)
        trechos = _juntar([r for r in achados if r.id in motivo_de], motivo_de, posicao)
        todos = self._videos(trechos, job, termos, ordem, cancelado)
        videos = todos[:limite]
        t_videos = _agora() - inicio
        if sistema is not None:
            self._assinar_os_quadros(videos, cancelado)
        candidatas = [
            (c, achados_da_clausula)
            for c, achados_da_clausula in zip(clausulas, resultados, strict=True)
            if c.pessoa_na_imagem
        ]
        # "Nenhuma aparição" fala do acervo, não do que a faceta deixou. Sem facetas, vale o
        # resultado da cláusula; com elas, a consulta de novo sem as facetas. As consultas
        # que podem ser precisas (as duas de menções e a sem facetas) vão ao índice juntas,
        # só a rede em paralelo; os Jobs são lidos depois, aqui. A consulta que já foi ao
        # índice nesta busca não vai de novo.
        pedidas: list[Consulta] = []
        for c, achados_da_clausula in candidatas:
            if sem_facetas and achados_da_clausula:
                continue
            quem = nome(c.pessoa_na_imagem) or ""
            for q in (
                *([] if sem_facetas else [c.consulta]),
                *_consultas_das_mencoes(quem, entendida),
            ):
                if q not in pedidas and all(q != p for p, _ in prontas):
                    pedidas.append(q)
        if pedidas:
            pool = ThreadPoolExecutor(
                max_workers=max(1, min(TETO_DE_CONSULTAS_AO_INDICE, len(pedidas)))
            )

            def adiantada(q: Consulta) -> list[Registro] | None:
                # Pode nem fazer falta: o erro só conta se `consultar` precisar dela e
                # repetir a ida ao índice, como antes do #568.
                try:
                    return do_indice(q)
                except BuscaCancelada:
                    raise
                except Exception:
                    log.warning(
                        "consulta adiantada falhou; refeita se fizer falta",
                        exc_info=True,
                    )
                    return None

            try:
                prontas.extend(
                    (q, sem_excluidas(q, a))
                    for q, a in zip(pedidas, pool.map(adiantada, pedidas), strict=True)
                    if a is not None
                )
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        vazios = [
            self._sem_aparicao(
                nome(c.pessoa_na_imagem) or "", c.pessoa_na_imagem, entendida, consultar
            )
            for c, achados_da_clausula in candidatas
            if not (achados_da_clausula if sem_facetas else consultar(c.consulta))
        ]
        log.info(
            "busca em %d ms: %d vídeos, %d clausulas; desde o início: entender %d ms, "
            "índice %d ms, jobs %d ms, nomes %d ms, fusão %d ms, ranking %d ms, vídeos %d ms",
            (_agora() - inicio) * 1000,
            len(videos),
            len(clausulas),
            t_entender * 1000,
            t_indice * 1000,
            t_jobs * 1000,
            t_nomes * 1000,
            t_fusao * 1000,
            t_ranking * 1000,
            t_videos * 1000,
        )
        agora = self._relogio()
        resultado = ResultadoDaBusca(
            entendida=Entendida(
                evidencias=list(entendida.evidencias),
                programa=entendida.programa,
                desde=entendida.exibido_desde,
                ate=entendida.exibido_ate,
                termo_da_foto=entendida.saneada if termo_da_foto else None,
            ),
            videos=videos,
            sem_aparicoes=vazios,
            plano_b=False,
            facetas=_facetas([r for r, _, _ in fundidos], nome),
            quadros_expiram_em=agora + VALIDADE_INFORMADA_DA_IMAGEM,
        )
        if len(todos) > limite:
            resultado._proximo_cursor = self._guardar(
                resultado, todos, termos, dono, impressao, limite, versao
            )
        return resultado

    def _reordenar(
        self, impressao: str, texto: str, registros: list[Registro]
    ) -> list[Registro]:
        """A Ranking API com cache: a chave leva os IDs enviados, então um vídeo que saiu
        (lixeira) pede um ranking novo; só a ordem dos IDs fica guardada."""
        ids = self._candidatos.obter(
            ("ranking", impressao, texto, tuple(r.id for r in registros)),
            lambda: [r.id for r in self._ranking.reordenar(texto, registros)],
        )
        por_id = {r.id: r for r in registros}
        return [por_id[i] for i in ids if i in por_id]

    def _guardar(
        self,
        resultado: ResultadoDaBusca,
        todos: list[VideoDoResultado],
        termos: list[str],
        dono: str,
        impressao: str,
        limite: int,
        versao: int,
    ) -> str | None:
        """Grava a lista inteira e devolve o cursor da 2ª página."""
        agora = self._relogio()
        lista = ListaDaBusca(
            dono=dono,
            impressao=impressao,
            criado_em=agora,
            expira_em=agora + VALIDADE_DA_LISTA,
            entendida=resultado.entendida,
            sem_aparicoes=resultado.sem_aparicoes,
            plano_b=resultado.plano_b,
            facetas=resultado.facetas,
            termos=termos,
            versao_da_lixeira=versao,
            videos=[
                VideoGuardado(
                    job_id=v.job_id,
                    momentos=[
                        MomentoGuardado(
                            tipo=m.tipo,
                            inicio_ms=m.inicio_ms,
                            fim_ms=m.fim_ms,
                            motivo=m.motivo,
                            quadro=m.quadro,
                        )
                        for m in v.momentos
                    ],
                )
                for v in todos
            ],
        )
        # ponytail: 500 momentos com o texto máximo (2.000 caracteres) cabem com folga
        # depois de comprimidos; se um dia não couberem, a lista perde o fim até caber.
        while (
            len(lista.para_documento()["conteudo"]) > TETO_DA_LISTA_BYTES
            and len(lista.videos) > limite
        ):
            corte = max(limite, len(lista.videos) * 3 // 4)
            log.warning("lista da busca grande demais: fica com %d vídeos", corte)
            lista = lista.model_copy(update={"videos": lista.videos[:corte]})
        if len(lista.videos) <= limite:
            return None
        return f"{self._listas.gravar(lista.para_documento())}.{limite}"

    def _pagina_seguinte(
        self,
        cursor: str,
        limite: int,
        dono: str,
        impressao: str,
        sistema: str | None,
        cancelado: threading.Event | None,
    ) -> ResultadoDaBusca:
        """A fatia da lista guardada; os Jobs são relidos, e o vídeo que foi para a
        lixeira ou saiu do alcance do chamador desde a 1ª página fica de fora."""
        id, _, posicao = cursor.rpartition(".")
        # Só letras e números ASCII: um `/` no id viraria outro caminho no Firestore.
        if not (_ascii_alnum(id) and posicao.isascii() and posicao.isdigit()):
            raise CursorInvalido
        documento = self._listas.ler(id)
        try:
            lista = ListaDaBusca.do_documento(documento) if documento else None
        except (zlib.error, ValueError, KeyError, TypeError) as e:
            # Documento estragado: quem chama refaz a busca, como num cursor vencido.
            raise CursorInvalido from e
        agora = self._relogio()
        inicio = int(posicao)
        if (
            lista is None
            or lista.expira_em <= agora  # o TTL do Firestore apaga com atraso
            or lista.dono != dono
            or lista.impressao != impressao
            or not 0 < inicio < len(lista.videos)
            # A lixeira do catálogo mudou (ou a lista é do formato sem versão): a lista
            # guarda quem contava então (#598).
            or lista.versao_da_lixeira != self._versao.atual()
        ):
            raise CursorInvalido
        fim = inicio + limite
        guardados = lista.videos[inicio:fim]
        lidos = {
            j.id: j
            for j in self._repositorio.obter_varios([v.job_id for v in guardados])
        }
        videos: list[VideoDoResultado] = []
        for v in guardados:
            j = self._visivel_de(lidos.get(v.job_id), sistema)
            if j is None:
                continue
            momentos = [
                Momento(
                    **m.model_dump(),
                    destaques=_destaques(m.motivo, lista.termos),
                    quadro_url=None,
                )
                for m in v.momentos
            ]
            videos.append(
                VideoDoResultado(
                    job_id=v.job_id,
                    nome=j.nome,
                    programa=j.programa,
                    data_exibicao=j.data_exibicao,
                    duracao_s=j.duracao_s,
                    n_momentos=len(momentos),
                    momentos=momentos,
                )
            )
        if sistema is not None:
            self._assinar_os_quadros(videos, cancelado)
        resultado = ResultadoDaBusca(
            entendida=lista.entendida,
            videos=videos,
            sem_aparicoes=lista.sem_aparicoes,
            plano_b=lista.plano_b,
            facetas=lista.facetas,
            quadros_expiram_em=agora + VALIDADE_INFORMADA_DA_IMAGEM,
        )
        if fim < len(lista.videos):
            resultado._proximo_cursor = f"{id}.{fim}"
        return resultado

    def _visivel(self, job_id: str, sistema: str | None) -> Job | None:
        """O vídeo, se concluído, fora da lixeira e, para uma chave de sistema, do mesmo sistema."""
        return self._visivel_de(self._repositorio.obter(job_id), sistema)

    @staticmethod
    def _visivel_de(achado: Job | None, sistema: str | None) -> Job | None:
        if achado is None or achado.estado != "concluido" or achado.lixeira:
            return None
        if sistema is not None and achado.sistema != sistema:
            return None
        return achado

    def _termo_da_foto(self, jpeg: bytes) -> str:
        try:
            termo = termo_da_foto(jpeg, transporte=self._transporte)
        except (ErroHttp, ValueError) as e:
            log.warning("termo da foto não obtido (%s)", e)
            raise BuscaPorImagemIndisponivel from e
        if not termo:
            raise BuscaPorImagemIndisponivel
        return termo

    def _clausulas(
        self,
        e: ConsultaEntendida,
        nome: Callable[[str | None], str | None],
        contam: Collection[str],
    ) -> list[_Clausula]:
        base = _base(e)
        clausulas: list[_Clausula] = []
        for pessoa in e.pessoas:
            clausulas.extend(
                _clausulas_da_pessoa(pessoa, e, base, nome, pessoa in contam)
            )
        if livre := _texto_da_busca(e):
            tipos: list[TipoDeRegistro | None] = []
            por_evidencia: tuple[tuple[EvidenciaDaBusca, TipoDeRegistro], ...] = (
                ("imagem", "plano"),
                ("fala", "fala"),
                ("gc", "texto_na_tela"),
                ("objeto", "objeto"),
                ("marca", "objeto"),
                ("citada", "fala"),
                ("citada", "texto_na_tela"),
            )
            for evidencia, tipo in por_evidencia:
                if evidencia in e.evidencias and tipo not in tipos:
                    tipos.append(tipo)
            for tipo_do_texto in tipos or [None]:
                clausulas.append(
                    _Clausula(
                        Consulta(
                            filtros=replace(base, tipo=tipo_do_texto),
                            texto=com_as_formas(livre),
                            significado=livre,
                            cortar_significado=True,
                        ),
                        lambda r: _motivo(r, nome),
                    )
                )
        return clausulas

    def _assinar_os_quadros(
        self,
        videos: list[VideoDoResultado],
        cancelado: threading.Event | None,
    ) -> None:
        """Só a chave de sistema recebe a URL assinada. Cada assinatura é uma ida ao IAM:
        vão em paralelo, até `TETO_DE_ASSINATURAS`, e o cancelamento é conferido antes de
        cada uma."""

        def assinar(video: VideoDoResultado, momento: Momento) -> None:
            assert momento.quadro is not None
            _conferir(cancelado)
            momento.quadro_url = self._armazenamento.url_do_quadro(
                video.job_id, momento.quadro, VALIDADE_DA_IMAGEM
            )

        pedidos = [(v, m) for v in videos for m in v.momentos if m.quadro]
        if not pedidos:
            return
        with ThreadPoolExecutor(max_workers=TETO_DE_ASSINATURAS) as pool:
            list(pool.map(assinar, *zip(*pedidos, strict=True)))

    def _videos(
        self,
        trechos: list[_Trecho],
        job: Callable[[str], Job | None],
        termos: list[str],
        ordem: Ordem,
        cancelado: threading.Event | None,
    ) -> list[VideoDoResultado]:
        por_video: dict[str, list[_Trecho]] = defaultdict(list)
        for t in trechos:
            por_video[t.job_id].append(t)
        videos: list[tuple[int, VideoDoResultado]] = []
        for id, lista in por_video.items():
            _conferir(cancelado)
            j = job(id)
            if j is None:
                continue
            # A relevância também dentro do vídeo; no empate, o tempo.
            lista.sort(key=lambda t: (t.posicao, t.inicio_ms, t.fim_ms))
            momentos = [
                Momento(
                    tipo=t.tipo,
                    inicio_ms=t.inicio_ms,
                    fim_ms=t.fim_ms,
                    motivo=t.motivo,
                    destaques=_destaques(t.motivo, termos),
                    quadro=t.quadro,
                    quadro_url=None,
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
        quem: str,
        pessoa: str | None,
        e: ConsultaEntendida,
        consultar: Callable[[Consulta], list[Registro]],
    ) -> SemAparicao:
        """Quantas vezes a pessoa sem aparição é citada, no mesmo programa e período."""
        fala, tela = _consultas_das_mencoes(quem, e)
        na_fala = consultar(fala)
        na_tela = consultar(tela)
        return SemAparicao(
            pessoa_id=pessoa,
            nome=quem,
            mencoes_na_fala=len(na_fala),
            mencoes_na_tela=len(na_tela),
        )


def _consultas_das_mencoes(
    quem: str, e: ConsultaEntendida
) -> tuple[Consulta, Consulta]:
    """O nome na fala e no texto na tela, no programa e período da busca, sem a frase."""
    base = _base(e)
    texto = normalizar(quem)
    return (
        Consulta(filtros=replace(base, tipo="fala"), texto=texto),
        Consulta(filtros=replace(base, tipo="texto_na_tela"), texto=texto),
    )


def _casa(r: Registro, a: Ajustes) -> bool:
    """O registro passa nas facetas de pessoa, marca e tipo que o editor clicou."""
    return (
        (a.pessoa is None or a.pessoa in r.pessoas or a.pessoa == r.dono)
        and (a.marca is None or r.marca == a.marca)
        and (a.tipo is None or r.tipo == a.tipo)
    )


def _sem_quem_nao_conta(
    r: Registro, contam: Collection[str], sem_marca: Collection[str]
) -> Registro:
    return replace(
        r,
        pessoas=[p for p in r.pessoas if p in contam],
        dono=r.dono if r.dono in contam else None,
        marca=None if r.marca and normalizar(r.marca) in sem_marca else r.marca,
    )


def _ainda_casa(r: Registro, f: Filtros) -> bool:
    """Os filtros de pessoa, dono e marca, que a exclusão pode ter deixado sem casar."""
    return (
        (f.pessoa is None or f.pessoa in r.pessoas)
        and (f.dono is None or f.dono == r.dono)
        and (f.marca is None or f.marca == r.marca)
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
    e o índice não agrega), então a conta é nossa e vai até `TETO_DE_REGISTROS` (500)
    candidatos fundidos (cada cláusula traz até 500, já com os filtros e as facetas no
    índice): o valor que só aparece além deles não entra, e as contagens são de
    "vídeos entre os 500 melhores registros", não do acervo todo.
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


def _ajustada(e: ConsultaEntendida, a: Ajustes) -> ConsultaEntendida:
    """Aplica os filtros da tela."""
    e = replace(e, evidencias=a.evidencias)
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
    return e.evidencias or ("imagem", "fala", "gc")


def _texto_da_busca(e: ConsultaEntendida) -> str:
    """O que vai à busca por texto e por significado: a frase das aspas e o resto, sem
    repetir a frase se ela já está no texto livre."""
    if e.frase_exata and e.texto_livre and _contem(e.texto_livre, e.frase_exata):
        return e.texto_livre
    return " ".join(p for p in (e.frase_exata, e.texto_livre) if p)


def _contem(texto: str, frase: str) -> bool:
    """A frase inteira no texto, com as palavras juntas e na ordem, sem acento nem maiúscula."""
    return f" {_no_singular(frase)} " in f" {_no_singular(texto)} "


def _no_singular(texto: str) -> str:
    return " ".join(normalizar(singular(p)) for p in re.findall(r"\w+", texto))


def _tem_a_frase(r: Registro, frase: str | None) -> bool:
    """A frase inteira, com as palavras juntas e na ordem, no texto ou na descrição."""
    if not frase:
        return True
    return any(_contem(c, frase) for c in (r.texto, r.descricao) if c)


def _clausulas_da_pessoa(
    pessoa: str,
    e: ConsultaEntendida,
    base: Filtros,
    nome: Callable[[str | None], str | None],
    conta: bool,
) -> list[_Clausula]:
    """A pessoa que não conta (lixeira do catálogo, #583) não gera a cláusula de aparição;
    o nome dela segue achado pelo texto."""
    quem = nome(pessoa)
    clausulas: list[_Clausula] = []
    evidencias = _evidencias(e)
    if "imagem" in evidencias and quem and conta:
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
        clausulas.extend(_clausulas_das_mencoes(quem, e, base, nome))
    return clausulas


def _clausulas_das_mencoes(
    quem: str,
    e: ConsultaEntendida,
    base: Filtros,
    nome: Callable[[str | None], str | None],
) -> list[_Clausula]:
    """O nome na fala e no texto na tela, quando as evidências pedidas os incluem."""
    evidencias = _evidencias(e)
    clausulas: list[_Clausula] = []
    if "fala" in evidencias or "citada" in evidencias:
        clausulas.append(
            _Clausula(
                Consulta(filtros=replace(base, tipo="fala"), texto=normalizar(quem)),
                lambda r: _motivo(r, nome),
            )
        )
    if "gc" in evidencias or "citada" in evidencias:
        clausulas.append(
            _Clausula(
                Consulta(
                    filtros=replace(base, tipo="texto_na_tela"), texto=normalizar(quem)
                ),
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


def _impressao(**partes: object) -> str:
    """A consulta e os filtros, sem o tamanho da página: o cursor só vale na mesma."""
    texto = json.dumps(partes, sort_keys=True, default=str)
    return hashlib.sha256(texto.encode()).hexdigest()


def _ascii_alnum(texto: str) -> bool:
    return texto.isascii() and texto.isalnum()


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
            r.job_id,
            r.inicio_ms,
            r.fim_ms,
            motivos[r.id],
            posicao[r.id],
            r.quadro,
            r.tipo,
        )
        abertos[chave] = atual
        trechos.append(atual)
    return trechos
