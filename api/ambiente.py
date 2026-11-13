"""Leitura obrigatória de variável de ambiente (só a biblioteca padrão, para entrar em qualquer imagem)."""

from collections.abc import Mapping


class FaltaNoAmbiente(Exception):
    pass


def exigir_do_ambiente(ambiente: Mapping[str, str], nome: str) -> str:
    if not ambiente.get(nome):
        raise FaltaNoAmbiente(f"{nome} não está no ambiente")
    return ambiente[nome]
