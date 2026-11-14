"""Erros de infraestrutura que várias camadas levantam e que o handler da aplicação vira 503.

Módulo leve: só a biblioteca padrão e o Google, nada do domínio, para quem lê a lixeira
(e o Quem conta, #610) não precisar importar o módulo de Jobs.
"""

from collections.abc import Callable

from google.api_core.exceptions import GoogleAPIError


class ServicoIndisponivel(Exception):
    """Porta ainda sem adaptador real."""


def lido[T](ler: Callable[[], T]) -> T:
    """Uma leitura do Firestore que falha vira 503 (`ServicoIndisponivel`), não 500."""
    try:
        return ler()
    except GoogleAPIError as e:
        raise ServicoIndisponivel(str(e)) from e
