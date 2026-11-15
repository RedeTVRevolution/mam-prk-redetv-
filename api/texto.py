"""Texto comparável: só a biblioteca padrão, para entrar nas imagens com GPU."""

import unicodedata


def sem_acento(texto: str) -> str:
    """Tira só as marcas de acento (NFKD); o resto do texto fica como está."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )


def normalizar(texto: str) -> str:
    """Sem diferenciar maiúsculas, acentos nem espaços repetidos."""
    return " ".join(sem_acento(texto).casefold().split())
