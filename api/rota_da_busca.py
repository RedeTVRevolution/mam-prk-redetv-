"""A rota `/v1/busca` (#120): permissão, limites de uso e tempo máximo; a busca é `busca.py`."""

import logging
from collections import defaultdict, deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TempoEsgotado
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import Chamador, Sistema
from api.busca import (
    TETO_DE_VIDEOS,
    VIDEOS_POR_PADRAO,
    Busca,
    Ordem,
    ResultadoDaBusca,
    filtros_do_servidor,
)
from api.jobs import _exige

log = logging.getLogger(__name__)

CONSULTAS_POR_MINUTO = 30
TEMPO_MAXIMO_S = 10.0

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="busca")


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

    def consumir(self, quem: str) -> bool:
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
) -> APIRouter:
    rotas = APIRouter()
    limite = LimiteDeConsultas(consultas_por_minuto, relogio)

    @rotas.get("/busca")
    def buscar(
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        q: Annotated[str, Query(min_length=1, max_length=1000)],
        ordem: Ordem = "relevancia",
        limite_de_videos: Annotated[
            int, Query(alias="limite", ge=1, le=TETO_DE_VIDEOS)
        ] = VIDEOS_POR_PADRAO,
    ) -> ResultadoDaBusca:
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
            limite=limite_de_videos,
            filtros_do_servidor=filtros_do_servidor(),
            sistema=sistema,
        )
        try:
            return futuro.result(timeout=tempo_maximo_s)
        except TempoEsgotado:
            futuro.cancel()
            log.warning("busca passou de %.1f s", tempo_maximo_s)
            raise HTTPException(504, "A busca demorou demais") from None

    return rotas
