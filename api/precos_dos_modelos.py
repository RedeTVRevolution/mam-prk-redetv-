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


def lista_de_pares[T: (int, float)](
    texto: str, tipo: type[T], mensagem: str
) -> dict[str, tuple[T, T]]:
    """`chave=a:b` separados por vírgula; `tipo` lê os dois valores. O item inválido levanta
    `FaltaNoAmbiente` com `mensagem: 'item'`."""
    lidos: dict[str, tuple[T, T]] = {}
    for item in filter(None, (p.strip() for p in texto.split(","))):
        chave, _, valores = item.partition("=")
        a, _, b = valores.partition(":")
        try:
            lidos[chave] = (tipo(a), tipo(b))
        except ValueError as e:
            raise FaltaNoAmbiente(f"{mensagem}: {item!r}") from e
    return lidos


def precos_do_ambiente(texto: str) -> dict[str, Preco]:
    lidos = lista_de_pares(texto, float, "preço inválido em PRECOS_DOS_MODELOS")
    return {modelo: Preco(*valores) for modelo, valores in lidos.items()}


def tokens_do_transporte(transporte: Transporte) -> tuple[int, int]:
    return (
        getattr(transporte, "tokens_de_entrada", 0),
        getattr(transporte, "tokens_de_saida", 0),
    )
