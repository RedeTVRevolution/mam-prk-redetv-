"""Texto comparável: só a biblioteca padrão, para entrar nas imagens com GPU."""

import unicodedata


def normalizar(texto: str) -> str:
    """Sem diferenciar maiúsculas, acentos nem espaços repetidos."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.casefold().split())
