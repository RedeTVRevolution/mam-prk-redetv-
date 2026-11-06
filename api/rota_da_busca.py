"""A rota `/v1/busca` (#120): permissão, limites de uso e tempo máximo; a busca é `busca.py`."""

import logging
import threading
from collections import defaultdict, deque
from collections.abc import AsyncGenerator, Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TempoEsgotado
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from api.auth import Chamador, Sistema
from api.busca import (
    TETO_DE_VIDEOS,
    VIDEOS_POR_PADRAO,
    Ajustes,
    Busca,
    BuscaPorImagemIndisponivel,
    EvidenciaDaBusca,
    Ordem,
    PlanoSemVetor,
    ResultadoDaBusca,
    filtros_do_servidor,
)
from api.entendimento_da_consulta import TEMPO_DA_CONSULTA_S
from api.eventos_de_uso import Eventos, Filtro, SemEventos, quem_do_chamador, registrar
from api.imagens_hostis import (
    AcimaDoLimiteDeBytes,
    AcimaDoLimiteDePixels,
    ImagemRecusada,
    recodificar,
)
from api.indice_da_busca import TipoDeRegistro
from api.jobs import CursorInvalido, _exige

log = logging.getLogger(__name__)

CONSULTAS_POR_MINUTO = 30
# Descrição das rotas da busca no OpenAPI, para os sistemas (docs/Plano_MAM.md, "Busca").
NOTA_DO_QUADRO = (
    "Cada momento traz `quadro`, o caminho do quadro no vídeo (`quadros/plano-6.jpg`): "
    "peça a URL em `GET /v1/jobs/{job_id}/quadros/{arquivo}`, com o nome do arquivo "
    "(`plano-6.jpg`). O `quadro_url` assinado, que só a chave "
    "de sistema recebe, é obsoleto e vai sair da resposta."
)
# Acima do teto do modelo, para que o plano B chegue ao usuário antes do 504.
TEMPO_MAXIMO_S = TEMPO_DA_CONSULTA_S + 5.0

# A foto da busca por imagem é entrada hostil (#270): só JPEG ou PNG, pelo conteúdo.
FORMATOS_DA_BUSCA_POR_IMAGEM = frozenset({"JPEG", "PNG"})
# Folga do multipart (cabeçalhos das partes) acima do limite do arquivo.
FOLGA_DO_MULTIPART = 4096

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="busca")


@dataclass(frozen=True)
class LimitesDaImagem:
    max_bytes: int = 5_000_000
    max_pixels: int = 25_000_000


LIMITES_DA_IMAGEM = LimitesDaImagem()


class LimiteDeConsultas:
    """Consultas por minuto de cada usuário (ou sistema), contadas nesta instância."""

    def __init__(
        self,
        maximo: int,
        relogio: Callable[[], datetime],
        janela: timedelta = timedelta(minutes=1),
    ) -> None:
        self._maximo = maximo
        self._relogio = relogio
        self._janela = janela
        self._feitas: dict[str, deque[datetime]] = defaultdict(deque)
        self._trava = threading.Lock()  # a rota é síncrona: roda em várias threads

    def consumir(self, quem: str) -> bool:
        with self._trava:
            agora = self._relogio()
            feitas = self._feitas[quem]
            while feitas and agora - feitas[0] >= self._janela:
                feitas.popleft()
            if len(feitas) >= self._maximo:
                return False
            feitas.append(agora)
            return True


def _quem_e(chamador: Chamador) -> tuple[str | None, str]:
    """O sistema que filtra os vídeos (só de uma chave de sistema) e quem gasta o limite."""
    if isinstance(chamador, Sistema):
        return chamador.sistema, f"sistema:{chamador.sistema}"
    return None, chamador.uid


def criar_rotas_da_busca(
    busca: Busca,
    relogio: Callable[[], datetime],
    consultas_por_minuto: int = CONSULTAS_POR_MINUTO,
    tempo_maximo_s: float = TEMPO_MAXIMO_S,
    limites_da_imagem: LimitesDaImagem = LIMITES_DA_IMAGEM,
    eventos: Eventos | None = None,
) -> APIRouter:
    rotas = APIRouter()
    publicador = eventos or SemEventos()
    limite = LimiteDeConsultas(consultas_por_minuto, relogio)

    def registrar_busca(
        chamador: Chamador,
        tamanho: int | None,
        programa: str | None,
        resultado: ResultadoDaBusca,
        job_id: str | None = None,
        **filtros: object,
    ) -> None:
        """Só o tamanho da consulta e os filtros que a pessoa pôs; o texto fica aqui."""
        registrar(
            publicador,
            "busca",
            quem_do_chamador(chamador),
            relogio(),
            job_id=job_id,
            programa=programa,
            tamanho_da_consulta=tamanho,
            n_resultados=len(resultado.videos),
            filtros=[
                Filtro(nome=nome, valor=str(valor))
                for nome, valor in filtros.items()
                # `is`, não `in`: com `in`, o 0 sumiria junto com o False.
                if valor is not None and valor is not False and valor != ""
            ],
        )

    @rotas.get("/busca", description=f"Busca por texto. {NOTA_DO_QUADRO}")
    def buscar(
        resposta: Response,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        q: Annotated[str, Query(min_length=1, max_length=1000)],
        ordem: Ordem = "relevancia",
        evidencias: Annotated[list[EvidenciaDaBusca] | None, Query(alias="ev")] = None,
        programa: Annotated[str | None, Query(max_length=100)] = None,
        desde: date | None = None,
        ate: date | None = None,
        sem_periodo: bool = False,
        pessoa: Annotated[str | None, Query(max_length=100)] = None,
        marca: Annotated[str | None, Query(max_length=100)] = None,
        tipo: TipoDeRegistro | None = None,
        visual: bool = False,
        limite_de_videos: Annotated[
            int, Query(alias="limite", ge=1, le=TETO_DE_VIDEOS)
        ] = VIDEOS_POR_PADRAO,
        cursor: Annotated[str | None, Query(max_length=100)] = None,
    ) -> ResultadoDaBusca:
        if desde and ate and desde > ate:
            raise HTTPException(422, "O início do período passa do fim")
        sistema, quem = _quem_e(chamador)
        if not limite.consumir(quem):
            raise HTTPException(429, "Consultas demais; tente em um minuto")
        cancelado = threading.Event()
        futuro = _executor.submit(
            busca.buscar,
            q,
            ordem=ordem,
            visual=visual,
            limite=limite_de_videos,
            filtros_do_servidor=filtros_do_servidor(),
            sistema=sistema,
            cancelado=cancelado,
            cursor=cursor,
            dono=quem,
            ajustes=Ajustes(
                evidencias=tuple(dict.fromkeys(evidencias or ())),
                programa=programa,
                desde=desde,
                ate=ate,
                sem_periodo=sem_periodo,
                pessoa=pessoa,
                marca=marca,
                tipo=tipo,
            ),
        )
        try:
            resultado = futuro.result(timeout=tempo_maximo_s)
        except TempoEsgotado:
            futuro.cancel()
            cancelado.set()
            log.warning("busca passou de %.1f s", tempo_maximo_s)
            raise HTTPException(504, "A busca demorou demais") from None
        except CursorInvalido:
            raise HTTPException(422, "Cursor inválido") from None
        if cursor is None:  # a página seguinte não conta como busca nova
            registrar_busca(
                chamador,
                len(q),
                programa,
                resultado,
                modo="texto",
                ordem=ordem,
                evidencias=",".join(dict.fromkeys(evidencias or ())),
                desde=desde,
                ate=ate,
                sem_periodo=sem_periodo,
                pessoa=pessoa,
                marca=marca,
                tipo=tipo,
                visual=visual,
            )
        return _com_cursor(resposta, resultado)

    teto_do_corpo = limites_da_imagem.max_bytes + FOLGA_DO_MULTIPART

    async def foto_enviada(request: Request) -> bytes:
        """O arquivo do multipart, lido com teto e só em memória.

        O `File()` do FastAPI leria o corpo inteiro antes da rota, sem limite, e passaria
        de 1 MB para um arquivo temporário em disco: aqui o `Content-Length` é conferido
        antes de ler, a leitura para no teto e o arquivo nunca sai da memória.
        """
        try:
            declarado = int(request.headers["content-length"])
        except (KeyError, ValueError):
            raise HTTPException(411, "Envie o tamanho do pedido") from None
        if declarado > teto_do_corpo:
            raise HTTPException(422, _GRANDE_DEMAIS)

        async def corpo() -> AsyncGenerator[bytes, None]:
            lido = 0
            async for pedaco in request.stream():
                lido += len(pedaco)
                if lido > teto_do_corpo:
                    raise HTTPException(422, _GRANDE_DEMAIS)
                yield pedaco

        parser = MultiPartParser(request.headers, corpo(), max_files=1, max_fields=0)
        parser.spool_max_size = teto_do_corpo
        try:
            formulario = await parser.parse()
        except (MultiPartException, KeyError):
            raise HTTPException(422, _RECUSA) from None
        try:
            arquivo = formulario.get("arquivo")
            if not isinstance(arquivo, UploadFile):
                raise HTTPException(422, "Envie a imagem no campo arquivo")
            return await arquivo.read(limites_da_imagem.max_bytes + 1)
        finally:
            await formulario.close()

    @rotas.post("/busca/imagem", description=f"Busca por imagem. {NOTA_DO_QUADRO}")
    def buscar_por_imagem(
        resposta: Response,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        dados: Annotated[bytes, Depends(foto_enviada)],
        programa: Annotated[str | None, Query(max_length=100)] = None,
        desde: date | None = None,
        ate: date | None = None,
        sem_periodo: bool = False,
        limite_de_videos: Annotated[
            int, Query(alias="limite", ge=1, le=TETO_DE_VIDEOS)
        ] = VIDEOS_POR_PADRAO,
        cursor: Annotated[str | None, Query(max_length=100)] = None,
    ) -> ResultadoDaBusca:
        if desde and ate and desde > ate:
            raise HTTPException(422, "O início do período passa do fim")
        sistema, quem = _quem_e(chamador)
        if not limite.consumir(quem):
            raise HTTPException(429, "Consultas demais; tente em um minuto")
        # A foto fica só em memória: nunca no disco, no Storage, no Firestore nem nos logs.
        try:
            jpeg = recodificar(
                dados,
                max_bytes=limites_da_imagem.max_bytes,
                max_pixels=limites_da_imagem.max_pixels,
                formatos=FORMATOS_DA_BUSCA_POR_IMAGEM,
            )
        except AcimaDoLimiteDeBytes:
            raise HTTPException(422, _GRANDE_DEMAIS) from None
        except AcimaDoLimiteDePixels:
            raise HTTPException(422, _PIXELS_DEMAIS) from None
        except ImagemRecusada:
            raise HTTPException(422, _RECUSA) from None
        cancelado = threading.Event()
        futuro = _executor.submit(
            busca.buscar,
            "",
            imagem=jpeg,
            limite=limite_de_videos,
            filtros_do_servidor=filtros_do_servidor(),
            sistema=sistema,
            cancelado=cancelado,
            cursor=cursor,
            dono=quem,
            ajustes=Ajustes(
                programa=programa, desde=desde, ate=ate, sem_periodo=sem_periodo
            ),
        )
        # Dois passos do modelo em série (descrever a foto e entender o termo), cada um com o
        # seu teto: o prazo cobre os dois, para o plano B do entendimento chegar antes do 504.
        prazo_s = tempo_maximo_s + TEMPO_DA_CONSULTA_S
        try:
            resultado = futuro.result(timeout=prazo_s)
        except TempoEsgotado:
            futuro.cancel()
            cancelado.set()
            log.warning("busca por imagem passou de %.1f s", prazo_s)
            raise HTTPException(504, "A busca demorou demais") from None
        except CursorInvalido:
            raise HTTPException(422, "Cursor inválido") from None
        except BuscaPorImagemIndisponivel:
            raise HTTPException(
                503, "A busca por imagem não está disponível agora"
            ) from None
        if cursor is None:  # a página seguinte não conta como busca nova
            registrar_busca(
                chamador,
                len(dados),
                programa,
                resultado,
                modo="imagem",
                desde=desde,
                ate=ate,
                sem_periodo=sem_periodo,
            )
        return _com_cursor(resposta, resultado)

    @rotas.get("/busca/parecidos/planos")
    def planos_com_vetor(
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        job: Annotated[str, Query(min_length=1, max_length=100)],
    ) -> dict[str, list[int]]:
        """Os planos do vídeo que têm vetor do quadro: só neles "parecidos" aparece.

        Não gasta o limite de consultas por minuto: o Visualizador a chama ao abrir
        cada vídeo, e isso não deve tirar a vez das buscas de quem está ali.
        """
        sistema, _ = _quem_e(chamador)
        futuro = _executor.submit(busca.planos_com_vetor, job, sistema)
        try:
            planos = futuro.result(timeout=tempo_maximo_s)
        except TempoEsgotado:
            futuro.cancel()
            log.warning("lista dos planos com vetor passou de %.1f s", tempo_maximo_s)
            raise HTTPException(504, "A busca demorou demais") from None
        return {"planos": sorted(planos)}

    @rotas.get(
        "/busca/parecidos", description=f"Busca de planos parecidos. {NOTA_DO_QUADRO}"
    )
    def buscar_parecidos(
        resposta: Response,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        job: Annotated[str, Query(min_length=1, max_length=100)],
        plano: Annotated[int, Query(ge=0)],
        limite_de_videos: Annotated[
            int, Query(alias="limite", ge=1, le=TETO_DE_VIDEOS)
        ] = VIDEOS_POR_PADRAO,
        cursor: Annotated[str | None, Query(max_length=100)] = None,
    ) -> ResultadoDaBusca:
        sistema, quem = _quem_e(chamador)
        if not limite.consumir(quem):
            raise HTTPException(429, "Consultas demais; tente em um minuto")
        cancelado = threading.Event()
        futuro = _executor.submit(
            busca.buscar_parecidos,
            job,
            plano,
            limite=limite_de_videos,
            filtros_do_servidor=filtros_do_servidor(),
            sistema=sistema,
            cancelado=cancelado,
            cursor=cursor,
            dono=quem,
        )
        try:
            resultado = futuro.result(timeout=tempo_maximo_s)
        except TempoEsgotado:
            futuro.cancel()
            cancelado.set()
            log.warning("busca de parecidos passou de %.1f s", tempo_maximo_s)
            raise HTTPException(504, "A busca demorou demais") from None
        except CursorInvalido:
            raise HTTPException(422, "Cursor inválido") from None
        except PlanoSemVetor:
            raise HTTPException(404, _PLANO_SEM_VETOR) from None
        # Não há consulta: o ponto de partida é o plano de um vídeo.
        if cursor is None:  # a página seguinte não conta como busca nova
            registrar_busca(
                chamador, None, None, resultado, job, modo="parecidos", plano=plano
            )
        return _com_cursor(resposta, resultado)

    return rotas


def _com_cursor(resposta: Response, resultado: ResultadoDaBusca) -> ResultadoDaBusca:
    """O cursor da página seguinte no cabeçalho, como no acervo; some na última página."""
    if resultado._proximo_cursor:
        resposta.headers["X-Proximo-Cursor"] = resultado._proximo_cursor
    return resultado


_RECUSA = "Envie uma imagem JPEG ou PNG válida"
_GRANDE_DEMAIS = "A imagem passa do tamanho máximo"
_PIXELS_DEMAIS = "A imagem passa do tamanho máximo em pixels"
# Numa linha só: o teste do OpenAPI dos sistemas procura a mensagem inteira no código.
_PLANO_SEM_VETOR = "Este plano não tem vetor do quadro (vídeo indexado antes da busca por imagem, ou índice do quadro desligado), ou o vídeo não foi encontrado"
