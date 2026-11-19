"""Variantes de grafia de nomes próprios: "Lordelo" e "Lordello" são o mesmo nome.

A chave junta as grafias que só mudam na escrita (ph/f, th/t, y/i, k/c, w/v e letra dobrada)
e deixa as vogais, para Bruno continuar diferente de Bruna. Só vale para os nomes da lista
(os do acervo, `infra/modulos/mam/nomes_do_acervo.tf`): nas palavras comuns a chave erra
(carro/caro, para/parra).
"""

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from api.relatorios import config_e_transporte_do_ambiente, linhas_da_consulta
from api.texto import normalizar

_TROCAS = (("ph", "f"), ("th", "t"), ("y", "i"), ("k", "c"), ("w", "v"))


def _chave(palavra: str) -> str:
    p = normalizar(palavra)
    for de, para in _TROCAS:
        p = p.replace(de, para)
    return re.sub(r"(.)\1+", r"\1", p)


class Variantes:
    def __init__(self, nomes: Iterable[str] = ()) -> None:
        grupos: dict[str, set[str]] = defaultdict(set)
        for nome in nomes:
            grupos[_chave(nome)].add(normalizar(nome))
        self._grupo = {n: g for g in grupos.values() if len(g) > 1 for n in g}

    def de(self, palavra: str) -> set[str]:
        """As outras grafias da palavra, sem acento; vazio se ela não é nome da lista."""
        n = normalizar(palavra)
        return self._grupo.get(n, {n}) - {n}


def nomes_do_ambiente(ambiente: Any) -> Callable[[], list[str]] | None:
    """A leitura da tabela dos nomes do acervo, ou `None` se o ambiente não diz onde ela
    mora. Uma consulta lê a tabela inteira (poucos MB, uma vez por hora por instância)."""
    onde = config_e_transporte_do_ambiente(ambiente)
    if onde is None or "BIGQUERY_TABELA_DE_NOMES" not in ambiente:
        return None
    config, transporte = onde
    tabela = (
        f"`{config.projeto}.{config.dataset}.{ambiente['BIGQUERY_TABELA_DE_NOMES']}`"
    )

    def ler() -> list[str]:
        sql = f"SELECT palavra FROM {tabela}"
        linhas = linhas_da_consulta(
            transporte, config.regiao, sql, o_que="nomes do acervo"
        )
        return [linha[0] for linha in linhas]

    return ler
