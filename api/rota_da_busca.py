"""A rota `/v1/busca` (#120): permissão, limites de uso e tempo máximo; a busca é `busca.py`."""

import logging
import threading
from collections import defaultdict, deque
from collections.abc import AsyncGenerator, Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TempoEsgotado
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
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
    ResultadoDaBusca,
    TokenDaFotoInvalido,
    filtros_do_servidor,
)
from api.entendimento_da_consulta import TEMPO_DA_CONSULTA_S
from api.eventos_de_uso import Eventos, Filtro, SemEventos, quem_do_chamador, registrar
from api.imagens_hostis import (
    LIMITE_DE_BYTES_DO_ORIGINAL,
    LIMITE_DE_PIXELS_DO_ORIGINAL,
    AcimaDoLimiteDeBytes,
    AcimaDoLimiteDePixels,
    ImagemRecusada,
    recodificar,
)
from api.indice_da_busca import TipoDeRegistro
from api.modelo_do_job import CursorInvalido
from api.permissoes import exige_escopo
from api.teste_de_carga import CABECALHO_DE_TESTE, VALOR_DO_CABECALHO
from api.texto_como_dado import PADRAO_DA_LINHA, LinhaDaConsulta

log = logging.getLogger(__name__)

CONSULTAS_POR_MINUTO = 30
# O cabeçalho da carga fica fora do OpenAPI: não é parte do contrato para os sistemas.
TesteDeCarga = Annotated[
    str | None,
    Header(
        alias=CABECALHO_DE_TESTE,
        include_in_schema=False,
        max_length=16,
        pattern=PADRAO_DA_LINHA,
    ),
]


def consultas_por_minuto_do_ambiente(env: Mapping[str, str]) -> int:
    """O limite de `BUSCA_CONSULTAS_POR_MINUTO`; ausente ou vazia vale o padrão."""
    bruto = env.get("BUSCA_CONSULTAS_POR_MINUTO") or ""
    if not bruto:
        return CONSULTAS_POR_MINUTO
    try:
        valor = int(bruto)
    except ValueError:
        valor = 0
    if valor < 1:
        raise ValueError(
            f"BUSCA_CONSULTAS_POR_MINUTO deve ser um inteiro a partir de 1, veio {bruto!r}"
        )
    return valor


# O plano limita o texto da busca (docs/Plano_MAM.md); o campo do front tem o mesmo teto.
TAMANHO_DA_CONSULTA = 300
# Descrição das rotas da busca no OpenAPI, para os sistemas (docs/Plano_MAM.md, "Busca").
NOTA_DO_QUADRO = (
    "Cada momento traz `quadro`, o caminho do quadro no vídeo (`quadros/plano-6.jpg`): "
    "peça a URL em `GET /v1/jobs/{job_id}/quadros/{arquivo}`, com o nome do arquivo "
    "(`plano-6.jpg`). O `quadro_url` assinado, que só a chave "
    "de sistema recebe, é obsoleto e vai sair da resposta."
)
# Prazo da busca por texto, incluindo índice e ranking.
TEMPO_MAXIMO_S = 15.0

# A foto da busca por imagem é entrada hostil (#270): só JPEG ou PNG, pelo conteúdo.
FORMATOS_DA_BUSCA_POR_IMAGEM = frozenset({"JPEG", "PNG"})
# Folga do multipart (cabeçalhos das partes) acima do limite do arquivo.
FOLGA_DO_MULTIPART = 4096

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="busca")


@dataclass(frozen=True)
class LimitesDaImagem:
    max_bytes: int = LIMITE_DE_BYTES_DO_ORIGINAL
    max_pixels: int = LIMITE_DE_PIXELS_DO_ORIGINAL


LIMITES_DA_IMAGEM = LimitesDaImagem()


@dataclass(frozen=True)
class FotoEnviada:
    """O que o multipart trouxe: os bytes do `arquivo` ou o `token` de uma foto já descrita."""

    dados: bytes | None = None
    token: str | None = None


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
    aceita_teste_de_carga: bool = False,
) -> APIRouter:
    rotas = APIRouter()
    publicador = eventos or SemEventos()
    limite = LimiteDeConsultas(consultas_por_minuto, relogio)

    def da_carga(cabecalho: str | None) -> bool:
        """Só a chave ligada com o valor exato `1` tira a busca dos indicadores de uso."""
        return aceita_teste_de_carga and cabecalho == VALOR_DO_CABECALHO

    def registrar_busca(
        chamador: Chamador,
        tamanho: int | None,
        programa: str | None,
        resultado: ResultadoDaBusca,
        **filtros: object,
    ) -> None:
        """Só o tamanho da consulta e os filtros que a pessoa pôs; o texto fica aqui."""
        registrar(
            publicador,
            "busca",
            quem_do_chamador(chamador),
            relogio(),
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

    def consultar(
        resposta: Response,
        chamador: Chamador,
        *,
        desde: date | None,
        ate: date | None,
        cursor: str | None,
        limite_de_videos: int,
        prazo_s: float,
        da_carga_do_pedido: bool,
        preparar: Callable[[], dict[str, Any]],
        registrar_o_uso: Callable[[ResultadoDaBusca], None],
    ) -> ResultadoDaBusca:
        """A sequência das duas rotas: período, limite, busca com prazo, evento e cursor.

        `preparar` roda depois do limite (a foto só é recodificada para quem ainda tem
        cota) e devolve o `texto`, o `imagem`, o `ordem` e os `ajustes` da `busca.buscar`.
        """
        if desde and ate and desde > ate:
            raise HTTPException(422, "O início do período passa do fim")
        sistema, quem = _quem_e(chamador)
        if not limite.consumir(quem):
            raise HTTPException(429, "Consultas demais; tente em um minuto")
        entrada = preparar()
        cancelado = threading.Event()
        futuro = _executor.submit(
            busca.buscar,
            limite=limite_de_videos,
            filtros_do_servidor=filtros_do_servidor(),
            sistema=sistema,
            cancelado=cancelado,
            cursor=cursor,
            dono=quem,
            **entrada,
        )
        try:
            resultado = futuro.result(timeout=prazo_s)
        except TempoEsgotado:
            futuro.cancel()
            cancelado.set()
            log.warning("busca passou de %.1f s", prazo_s)
            raise HTTPException(504, "A busca demorou demais") from None
        except CursorInvalido:
            raise HTTPException(422, "Cursor inválido") from None
        if cursor is None and not da_carga_do_pedido:  # a 2ª página não é busca nova
            registrar_o_uso(resultado)
        return _com_cursor(resposta, resultado)

    @rotas.get("/busca", description=f"Busca por texto. {NOTA_DO_QUADRO}")
    def buscar(
        resposta: Response,
        chamador: Annotated[Chamador, Depends(exige_escopo("ler"))],
        q: Annotated[str, LinhaDaConsulta(TAMANHO_DA_CONSULTA, min_length=1)],
        ordem: Ordem = "relevancia",
        evidencias: Annotated[list[EvidenciaDaBusca] | None, Query(alias="ev")] = None,
        programa: Annotated[str | None, LinhaDaConsulta(100)] = None,
        desde: date | None = None,
        ate: date | None = None,
        pessoa: Annotated[str | None, LinhaDaConsulta(100)] = None,
        marca: Annotated[str | None, LinhaDaConsulta(100)] = None,
        tipo: TipoDeRegistro | None = None,
        limite_de_videos: Annotated[
            int, Query(alias="limite", ge=1, le=TETO_DE_VIDEOS)
        ] = VIDEOS_POR_PADRAO,
        cursor: Annotated[str | None, LinhaDaConsulta(100)] = None,
        teste_de_carga: TesteDeCarga = None,
    ) -> ResultadoDaBusca:
        return consultar(
            resposta,
            chamador,
            desde=desde,
            ate=ate,
            cursor=cursor,
            limite_de_videos=limite_de_videos,
            prazo_s=tempo_maximo_s,
            da_carga_do_pedido=da_carga(teste_de_carga),
            preparar=lambda: {
                "texto": q,
                "ordem": ordem,
                "ajustes": Ajustes(
                    evidencias=tuple(dict.fromkeys(evidencias or ())),
                    programa=programa,
                    desde=desde,
                    ate=ate,
                    pessoa=pessoa,
                    marca=marca,
                    tipo=tipo,
                ),
            },
            registrar_o_uso=lambda resultado: registrar_busca(
                chamador,
                len(q),
                programa,
                resultado,
                modo="texto",
                ordem=ordem,
                evidencias=",".join(dict.fromkeys(evidencias or ())),
                desde=desde,
                ate=ate,
                pessoa=pessoa,
                marca=marca,
                tipo=tipo,
            ),
        )

    teto_do_corpo = limites_da_imagem.max_bytes + FOLGA_DO_MULTIPART

    async def foto_enviada(request: Request) -> FotoEnviada:
        """O `arquivo` do multipart, ou o `token` no lugar dele, lido com teto e só em memória.

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

        parser = MultiPartParser(request.headers, corpo(), max_files=1, max_fields=1)
        parser.spool_max_size = teto_do_corpo
        try:
            formulario = await parser.parse()
        except (MultiPartException, KeyError):
            raise HTTPException(422, _RECUSA) from None
        try:
            arquivo = formulario.get("arquivo")
            token = formulario.get("token")
            if (arquivo is None) == (token is None):
                raise HTTPException(422, _UM_DOS_DOIS)
            if isinstance(token, str):
                return FotoEnviada(token=token)
            if not isinstance(arquivo, UploadFile):
                raise HTTPException(422, _UM_DOS_DOIS)
            return FotoEnviada(
                dados=await arquivo.read(limites_da_imagem.max_bytes + 1)
            )
        finally:
            await formulario.close()

    @rotas.post(
        "/busca/imagem",
        description=f"Busca por imagem. {NOTA_DO_QUADRO}",
        responses={
            200: {
                "headers": {
                    "X-Token-Da-Foto": {
                        "description": "O token da foto, na busca com o `arquivo` e sem "
                        "`cursor`.",
                        "schema": {"type": "string"},
                    }
                }
            }
        },
    )
    def buscar_por_imagem(
        resposta: Response,
        chamador: Annotated[Chamador, Depends(exige_escopo("ler"))],
        foto: Annotated[FotoEnviada, Depends(foto_enviada)],
        programa: Annotated[str | None, LinhaDaConsulta(100)] = None,
        desde: date | None = None,
        ate: date | None = None,
        limite_de_videos: Annotated[
            int, Query(alias="limite", ge=1, le=TETO_DE_VIDEOS)
        ] = VIDEOS_POR_PADRAO,
        cursor: Annotated[str | None, LinhaDaConsulta(100)] = None,
        teste_de_carga: TesteDeCarga = None,
    ) -> ResultadoDaBusca:

        def preparar() -> dict[str, Any]:
            # Com o token, a foto não sobe nem é decodificada: o termo vem do Firestore.
            if foto.dados is None:
                return {
                    "texto": "",
                    "token": foto.token,
                    "ajustes": Ajustes(programa=programa, desde=desde, ate=ate),
                }
            # A foto fica só em memória: nunca no disco, no Storage, no Firestore nem nos logs.
            try:
                jpeg = recodificar(
                    foto.dados,
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
            return {
                "texto": "",
                "imagem": jpeg,
                "ajustes": Ajustes(programa=programa, desde=desde, ate=ate),
            }

        try:
            resultado = consultar(
                resposta,
                chamador,
                desde=desde,
                ate=ate,
                cursor=cursor,
                limite_de_videos=limite_de_videos,
                # A foto tem uma chamada para a descrição, além do prazo da busca pelo termo.
                prazo_s=tempo_maximo_s + TEMPO_DA_CONSULTA_S,
                da_carga_do_pedido=da_carga(teste_de_carga),
                preparar=preparar,
                registrar_o_uso=lambda resultado: registrar_busca(
                    chamador,
                    len(foto.dados) if foto.dados is not None else None,
                    programa,
                    resultado,
                    modo="imagem",
                    desde=desde,
                    ate=ate,
                ),
            )
        except TokenDaFotoInvalido:
            raise HTTPException(422, TOKEN_INVALIDO) from None
        except BuscaPorImagemIndisponivel:
            raise HTTPException(
                503, "A busca por imagem não está disponível agora"
            ) from None
        if resultado._token_da_foto:
            resposta.headers["X-Token-Da-Foto"] = resultado._token_da_foto
        return resultado

    return rotas


def _com_cursor(resposta: Response, resultado: ResultadoDaBusca) -> ResultadoDaBusca:
    """O cursor da página seguinte no cabeçalho, como no acervo; some na última página."""
    if resultado._proximo_cursor:
        resposta.headers["X-Proximo-Cursor"] = resultado._proximo_cursor
    return resultado


# O texto que a tela compara para reenviar a foto (#802): não muda sem mudar a tela.
TOKEN_INVALIDO = "Token da foto inválido"
_UM_DOS_DOIS = "Envie a imagem no campo arquivo ou o token no campo token, só um deles"
_RECUSA = "Envie uma imagem JPEG ou PNG válida"
_GRANDE_DEMAIS = "A imagem passa do tamanho máximo"
_PIXELS_DEMAIS = "A imagem passa do tamanho máximo em pixels"
