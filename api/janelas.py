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
    return [
        Janela(
            indice=indice,
            inicio_ms=inicio,
            fim_ms=min(inicio + DURACAO_DA_JANELA_MS, duracao_ms),
            inicio_contexto_ms=max(inicio - CONTEXTO_MS, 0),
            fim_contexto_ms=min(
                inicio + DURACAO_DA_JANELA_MS + CONTEXTO_MS, duracao_ms
            ),
        )
        for indice, inicio in enumerate(range(0, duracao_ms, DURACAO_DA_JANELA_MS))
    ]
