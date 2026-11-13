"""Fábrica de sessão autenticada e o transporte REST único (spec #602, ADR 0021).

Módulo leve: só a autenticação do Google, para entrar em qualquer imagem. A autenticação
é resolvida na hora da chamada, pelo nome qualificado (`google.auth.default`), para os
testes que fazem patch no pacote do Google valerem sem mudança. Sem cache: quem guarda
a sessão hoje continua guardando.
"""

from collections.abc import Callable
from typing import Any

import google.auth
import google.auth.transport.requests

ESCOPO_DA_NUVEM = "https://www.googleapis.com/auth/cloud-platform"

# (método, caminho a partir da URL base, corpo) -> (status HTTP, resposta em JSON)
TransporteRest = Callable[[str, str, dict[str, Any] | None], tuple[int, dict[str, Any]]]


def sessao_autenticada(escopo: str = ESCOPO_DA_NUVEM) -> Any:
    """Uma `AuthorizedSession` nova, com as credenciais padrão (ADC) de quem roda."""
    credenciais, _ = google.auth.default(scopes=[escopo])
    return google.auth.transport.requests.AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]


def transporte_rest(
    url_base: str, escopo: str = ESCOPO_DA_NUVEM, timeout_s: float = 30
) -> TransporteRest:
    """O transporte REST real: `<url_base>/<caminho>`; resposta sem JSON vira `{}`."""
    sessao = sessao_autenticada(escopo)

    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        resposta = sessao.request(
            metodo, f"{url_base}/{caminho}", json=corpo, timeout=timeout_s
        )
        try:
            return resposta.status_code, resposta.json()
        except ValueError:
            return resposta.status_code, {}

    return transporte
