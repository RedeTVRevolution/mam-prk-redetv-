"""Espera de reenvio: backoff exponencial com jitter total."""

import random
from collections.abc import Callable


def espera_com_jitter(
    falhas: int,
    base_s: float,
    teto_s: float,
    sortear: Callable[[float], float] = lambda teto: random.uniform(0, teto),
) -> float:
    """Sorteia entre 0 e `min(teto, base * 2**falhas)`; `falhas` conta as já ocorridas."""
    return sortear(min(teto_s, base_s * 2**falhas))
