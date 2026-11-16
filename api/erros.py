"""Erros de infraestrutura que várias camadas levantam e que o handler da aplicação vira 503.

Módulo leve: só a biblioteca padrão e o Google, nada do domínio, para quem lê a lixeira
(e o Quem conta, #610) não precisar importar o módulo de Jobs.
"""

import logging
from collections.abc import Callable

from fastapi.responses import JSONResponse
from google.api_core.exceptions import GoogleAPIError

log = logging.getLogger(__name__)


class ServicoIndisponivel(Exception):
    """Porta ainda sem adaptador real."""


def resposta_de_indisponibilidade(erro: Exception) -> JSONResponse:
    """O 503 de toda rota e do middleware de autenticação, com a causa no log."""
    log.warning("serviço indisponível: %r", erro, exc_info=erro)
    return JSONResponse({"detail": "Serviço indisponível"}, status_code=503)


def lido[T](ler: Callable[[], T]) -> T:
    """Uma leitura do Firestore que falha vira 503 (`ServicoIndisponivel`), não 500."""
    try:
        return ler()
    except GoogleAPIError as e:
        raise ServicoIndisponivel(str(e)) from e
