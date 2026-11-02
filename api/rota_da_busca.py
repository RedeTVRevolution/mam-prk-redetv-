"""A rota `/v1/busca` (#120): permissão, limites de uso e tempo máximo; a busca é `busca.py`."""

import logging
import threading
from collections import defaultdict, deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TempoEsgotado
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

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
    filtros_do_servidor,
)
from api.entendimento_da_consulta import TEMPO_DA_CONSULTA_S
from api.imagens_hostis import ImagemRecusada, recodificar
from api.indice_da_busca import TipoDeRegistro
from api.jobs import _exige

log = logging.getLogger(__name__)

CONSULTAS_POR_MINUTO = 30
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


def criar_rotas_da_busca(
    busca: Busca,
    relogio: Callable[[], datetime],
    consultas_por_minuto: int = CONSULTAS_POR_MINUTO,
    tempo_maximo_s: float = TEMPO_MAXIMO_S,
    limites_da_imagem: LimitesDaImagem = LIMITES_DA_IMAGEM,
) -> APIRouter:
    rotas = APIRouter()
    limite = LimiteDeConsultas(consultas_por_minuto, relogio)

    @rotas.get("/busca")
    def buscar(
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
    ) -> ResultadoDaBusca:
        if desde and ate and desde > ate:
            raise HTTPException(422, "O início do período passa do fim")
        sistema = chamador.sistema if isinstance(chamador, Sistema) else None
        quem = (
            f"sistema:{chamador.sistema}"
            if isinstance(chamador, Sistema)
            else chamador.uid
        )
        if not limite.consumir(quem):
            raise HTTPException(429, "Consultas demais; tente em um minuto")
        futuro = _executor.submit(
            busca.buscar,
            q,
            ordem=ordem,
            visual=visual,
            limite=limite_de_videos,
            filtros_do_servidor=filtros_do_servidor(),
            sistema=sistema,
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
            return futuro.result(timeout=tempo_maximo_s)
        except TempoEsgotado:
            futuro.cancel()
            log.warning("busca passou de %.1f s", tempo_maximo_s)
            raise HTTPException(504, "A busca demorou demais") from None

    @rotas.post("/busca/imagem")
    def buscar_por_imagem(
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        arquivo: Annotated[UploadFile, File()],
        programa: Annotated[str | None, Query(max_length=100)] = None,
        desde: date | None = None,
        ate: date | None = None,
        sem_periodo: bool = False,
        limite_de_videos: Annotated[
            int, Query(alias="limite", ge=1, le=TETO_DE_VIDEOS)
        ] = VIDEOS_POR_PADRAO,
    ) -> ResultadoDaBusca:
        if desde and ate and desde > ate:
            raise HTTPException(422, "O início do período passa do fim")
        sistema = chamador.sistema if isinstance(chamador, Sistema) else None
        quem = (
            f"sistema:{chamador.sistema}"
            if isinstance(chamador, Sistema)
            else chamador.uid
        )
        if not limite.consumir(quem):
            raise HTTPException(429, "Consultas demais; tente em um minuto")
        # Lê um byte além do limite só para saber que passou; a foto fica em memória
        # (e no arquivo temporário do multipart, apagado ao fim do pedido), nunca no
        # Storage, no Firestore nem nos logs.
        dados = arquivo.file.read(limites_da_imagem.max_bytes + 1)
        try:
            jpeg = recodificar(
                dados,
                max_bytes=limites_da_imagem.max_bytes,
                max_pixels=limites_da_imagem.max_pixels,
                formatos=FORMATOS_DA_BUSCA_POR_IMAGEM,
            )
        except ImagemRecusada as e:
            raise HTTPException(422, _MOTIVOS_DA_RECUSA.get(str(e), _RECUSA)) from None
        futuro = _executor.submit(
            busca.buscar,
            "",
            imagem=jpeg,
            limite=limite_de_videos,
            filtros_do_servidor=filtros_do_servidor(),
            sistema=sistema,
            ajustes=Ajustes(
                programa=programa, desde=desde, ate=ate, sem_periodo=sem_periodo
            ),
        )
        try:
            return futuro.result(timeout=tempo_maximo_s)
        except TempoEsgotado:
            futuro.cancel()
            log.warning("busca por imagem passou de %.1f s", tempo_maximo_s)
            raise HTTPException(504, "A busca demorou demais") from None
        except BuscaPorImagemIndisponivel:
            raise HTTPException(
                503, "A busca por imagem não está disponível agora"
            ) from None

    return rotas


_RECUSA = "Envie uma imagem JPEG ou PNG válida"
_MOTIVOS_DA_RECUSA = {
    "acima do limite de bytes": "A imagem passa do tamanho máximo",
    "acima do limite de pixels": "A imagem passa do tamanho máximo em pixels",
}
