"""O acento de volta nas palavras comuns digitadas sem ele (#731).

O significado (embedding) e o Ranking acham mais com a grafia certa ("praça" acha o que
"praca" não acha). Só as palavras de `acentos.txt` mudam, com o acento e a caixa de lá; o
resto do texto fica como foi digitado. O texto lexical, os filtros e a frase exata não
passam por aqui.
"""

import logging
import re
from collections.abc import Collection
from functools import cache
from pathlib import Path

from api.texto import normalizar

log = logging.getLogger(__name__)

ARQUIVO = Path(__file__).with_name("acentos.txt")


@cache
def dicionario() -> dict[str, str]:
    """`grafia sem acento -> com acento`, lido uma vez por instância. Sem o arquivo, vazio:
    a busca segue com o texto digitado."""
    try:
        linhas = ARQUIVO.read_text("utf-8").splitlines()
    except (OSError, ValueError):
        log.warning(
            "dicionário de acentos não carregou; a busca segue sem ele", exc_info=True
        )
        return {}
    palavras = (p.strip() for p in linhas if not p.startswith("#"))
    return {normalizar(p): p for p in palavras if p}


def com_acento(texto: str, intocadas: Collection[str] = ()) -> str:
    """`texto` com o acento do dicionário nas palavras dele, menos as `intocadas` (sem
    acento nem maiúscula, como `normalizar` as deixa)."""
    acentos = dicionario()

    def trocar(m: re.Match[str]) -> str:
        chave = normalizar(m[0])
        return m[0] if chave in intocadas else acentos.get(chave, m[0])

    return re.sub(r"\w+", trocar, texto)
