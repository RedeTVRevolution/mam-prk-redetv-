"""Cliente do Gemini 3.5 Flash-Lite (Flex, endpoint global) para a decupagem.

A rede fica atrás de `Transporte`: aqui moram o pedido, a validação e as
tentativas. Esgotadas, levanta `AnaliseFalhou`, nunca devolve decupagem parcial.
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from api.decupagem import Decupagem

MODELO = "gemini-3.5-flash-lite"
TENTATIVAS_REDE = 5  # novas tentativas após 429/5xx
TENTATIVAS_ESQUEMA = 2  # novas tentativas após resposta fora do esquema
BACKOFF_BASE_S = 1.0
BACKOFF_TETO_S = 60.0


@dataclass(frozen=True)
class Pedido:
    modelo: str
    video_uri: str
    esquema: dict[str, Any]
    rotulos: dict[str, str]
    ferramentas: tuple[()] = ()  # o modelo nunca recebe ferramentas


class ErroHttp(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class AnaliseFalhou(Exception):
    codigo = "analise_falhou"


class Transporte(Protocol):
    def gerar(self, pedido: Pedido) -> str:
        """Devolve o texto JSON da resposta; levanta `ErroHttp` em falha HTTP."""
        ...


def _repetivel(status: int) -> bool:
    return status == 429 or status >= 500


def analisar(
    transporte: Transporte,
    *,
    video_uri: str,
    job_id: str,
    duracao_ms: int,
    dormir: Callable[[float], None] = time.sleep,
    sortear: Callable[[float], float] = lambda teto: random.uniform(0, teto),
) -> Decupagem:
    pedido = Pedido(
        modelo=MODELO,
        video_uri=video_uri,
        esquema=Decupagem.model_json_schema(),
        rotulos={"job_id": job_id},
    )
    falhas_rede = 0
    falhas_esquema = 0
    while True:
        try:
            texto = transporte.gerar(pedido)
        except ErroHttp as e:
            if not _repetivel(e.status) or falhas_rede >= TENTATIVAS_REDE:
                raise AnaliseFalhou() from e
            teto = min(BACKOFF_TETO_S, BACKOFF_BASE_S * 2**falhas_rede)
            dormir(sortear(teto))
            falhas_rede += 1
            continue
        try:
            return Decupagem.model_validate_json(
                texto, context={"duracao_ms": duracao_ms}
            )
        except ValidationError as e:
            if falhas_esquema >= TENTATIVAS_ESQUEMA:
                raise AnaliseFalhou() from e
            falhas_esquema += 1
