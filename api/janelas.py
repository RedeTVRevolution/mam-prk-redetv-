"""Plano de janelas de análise: divide a duração do vídeo em núcleos de 300 s.

Cada janela decupa o seu núcleo e vê 10 s de contexto de cada lado, limitado
ao vídeo. Tudo em milissegundos inteiros.
"""

from dataclasses import dataclass

DURACAO_DA_JANELA_MS = 300_000
CONTEXTO_MS = 10_000


@dataclass(frozen=True)
class Janela:
    indice: int
    inicio_ms: int
    fim_ms: int
    inicio_contexto_ms: int
    fim_contexto_ms: int


def planejar_janelas(duracao_ms: int) -> list[Janela]:
    """Núcleos contíguos de 300 s que cobrem o vídeo; o último pode ser mais curto.

    Duração zero não tem o que decupar e devolve lista vazia; duração negativa
    é erro de quem chamou.
    """
    if duracao_ms < 0:
        raise ValueError(f"duração negativa: {duracao_ms} ms")
    janelas = []
    for indice, inicio in enumerate(range(0, duracao_ms, DURACAO_DA_JANELA_MS)):
        fim = min(inicio + DURACAO_DA_JANELA_MS, duracao_ms)
        janelas.append(
            Janela(
                indice=indice,
                inicio_ms=inicio,
                fim_ms=fim,
                inicio_contexto_ms=max(inicio - CONTEXTO_MS, 0),
                fim_contexto_ms=min(fim + CONTEXTO_MS, duracao_ms),
            )
        )
    return janelas
