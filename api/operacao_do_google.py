"""Leitura única do `done` das operações de longa duração do Google.

Só biblioteca padrão: o `api/pre_voo.py` roda no CD sem instalar nada.
"""

from typing import Any


def terminou(operacao: dict[str, Any]) -> bool:
    """`done` ausente vale "não terminou" (o JSON do Google costuma omitir o `false`).

    A resposta sem `name` vale "terminou": não há operação para acompanhar (o `DELETE`
    sem corpo vira `{}`).
    """
    return "name" not in operacao or bool(operacao.get("done", False))
