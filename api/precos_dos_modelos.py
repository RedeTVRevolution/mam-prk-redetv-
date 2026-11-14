"""Preço por token dos modelos do Gemini, lido do ambiente (`PRECOS_DOS_MODELOS`).

Produção: a passada de comparação e a tela lado a lado usam; as ferramentas de medição também.
"""

from dataclasses import dataclass

from api.ambiente import FaltaNoAmbiente
from api.gemini import Transporte


@dataclass(frozen=True)
class Preco:
    entrada: float  # US$ por milhão de tokens
    saida: float


def precos_do_ambiente(texto: str) -> dict[str, Preco]:
    precos: dict[str, Preco] = {}
    for item in filter(None, (p.strip() for p in texto.split(","))):
        modelo, _, valores = item.partition("=")
        entrada, _, saida = valores.partition(":")
        try:
            precos[modelo] = Preco(float(entrada), float(saida))
        except ValueError as e:
            raise FaltaNoAmbiente(
                f"preço inválido em PRECOS_DOS_MODELOS: {item!r}"
            ) from e
    return precos


def tokens_do_transporte(transporte: Transporte) -> tuple[int, int]:
    return (
        getattr(transporte, "tokens_de_entrada", 0),
        getattr(transporte, "tokens_de_saida", 0),
    )
