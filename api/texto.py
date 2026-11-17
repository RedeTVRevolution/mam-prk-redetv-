"""Texto comparável: só a biblioteca padrão, para entrar nas imagens com GPU."""

import unicodedata
from functools import lru_cache


def sem_acento(texto: str) -> str:
    """Tira só as marcas de acento (NFKD); o resto do texto fica como está."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )


def normalizar(texto: str) -> str:
    """Sem diferenciar maiúsculas, acentos nem espaços repetidos."""
    return " ".join(sem_acento(texto).casefold().split())


@lru_cache(maxsize=8192)
def chave_da_marca(texto: str) -> str:
    """A grafia da marca sem maiúscula, acento, pontuação nem espaço: "RedeTV! Go" e
    "RedeTV GO" têm a mesma chave. Só letra e dígito contam; texto sem nenhum (`!!!`)
    fica como `normalizar` o deixa. Não é distância de edição: "Bolão na Rede" e "Bola na
    Rede" são marcas diferentes. `normalizar` não muda (vai gravada no Firestore)."""
    base = normalizar(texto)
    return "".join(c for c in base if c.isalnum()) or base
