"""O acento de volta nas palavras comuns digitadas sem ele (#731).

O significado (embedding) e o Ranking acham mais com a grafia certa ("praça" acha o que
"praca" não acha). Quem decide a grafia é a frequência das palavras no português, da
`wordfreq`: a palavra muda só quando uma grafia com acento é muito mais comum que todas
as outras com as mesmas letras. "praca" vira "praça"; "pais" (país ou pais), "esta" e
"coco" ficam. O texto lexical, os filtros e a frase exata não passam por aqui.
"""

import logging
import re
import threading
import unicodedata
from collections import defaultdict
from collections.abc import Collection
from functools import cache

from wordfreq import get_frequency_dict, get_frequency_list

from api.texto import normalizar

log = logging.getLogger(__name__)

# Quantas vezes a grafia com acento precisa ser mais comum que a segunda: "noticia" (7,8×)
# muda, "maca" (maçã 3,9×) e "pais" (país 2,5×) não.
RAZAO = 5
_montagem = threading.Lock()


def dicionario() -> dict[str, str]:
    """`grafia sem acento -> com acento`, montado uma vez por instância (~1 s), por uma
    thread só: o aquecimento e a 1ª busca não montam em dobro."""
    with _montagem:
        return _montar()


@cache
def _montar() -> dict[str, str]:
    """Sem os dados, vazio: a busca segue com o texto digitado."""
    try:
        frequencias = get_frequency_dict("pt", "best")
    except Exception:
        log.warning(
            "frequências do português não carregaram; a busca segue sem o acento",
            exc_info=True,
        )
        return {}
    grafias: defaultdict[str, list[tuple[float, str]]] = defaultdict(list)
    for palavra, frequencia in frequencias.items():
        # Só o acento volta: "2ª" e "1º" (NFKC muda) não substituem o "2a" digitado.
        if unicodedata.normalize("NFKC", palavra) == palavra:
            grafias[normalizar(palavra)].append((frequencia, palavra))
    acentos = {}
    for chave, opcoes in grafias.items():
        (primeira, palavra), *resto = sorted(opcoes, reverse=True)
        if palavra != chave and (not resto or primeira >= RAZAO * resto[0][0]):
            acentos[chave] = palavra
    # A wordfreq guarda as frequências para sempre (26 MB); o índice fica com 4 MB.
    get_frequency_dict.cache_clear()
    get_frequency_list.cache_clear()
    return acentos


def com_acento(texto: str, intocadas: Collection[str] = ()) -> str:
    """`texto` com o acento nas palavras comuns, menos as `intocadas` (sem acento nem
    maiúscula, como `normalizar` as deixa)."""
    acentos = dicionario()

    def trocar(m: re.Match[str]) -> str:
        chave = normalizar(m[0])
        return m[0] if chave in intocadas else acentos.get(chave, m[0])

    return re.sub(r"\w+", trocar, texto)
