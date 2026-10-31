"""Identidade de pessoas e de comerciais: a regra da consolidação das janelas.

A consolidação (#42, #45) e as correções (`api/correcoes.py`) casam itens por
estas funções: mudar a regra num lado e não no outro desalinha as correções.
"""

from api.comparador import normalizar

_NAO_IDENTIFICADO = normalizar("não identificado")


def nao_identificado(nome: str) -> bool:
    """O nome é o "não identificado" que o modelo usa para quem não reconhece,
    com ou sem a descrição curta que a instrução pede ("não identificado,
    repórter de cabelo curto")."""
    return normalizar(nome).startswith(_NAO_IDENTIFICADO)


def identidade_do_nome(nome: str) -> str | None:
    """O nome normalizado; `None` para "não identificado", que não distingue
    ninguém e nunca se une a outra pessoa."""
    return None if nao_identificado(nome) else normalizar(nome)


def identidade_do_comercial(marca: str, tipo: str) -> str:
    """Marca normalizada e tipo: dois comerciais iguais são o mesmo."""
    return f"{normalizar(marca)}|{tipo}"
