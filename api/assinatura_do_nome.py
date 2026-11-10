"""A assinatura de um nome (#544): a chave única para comparar nomes de objetos.

Normaliza (`normalizar`), separa as palavras, tira as vazias, passa cada uma ao singular
(`singular`, até estabilizar), tira a que repete a cor do item e ordena. É a chave do
dicionário de tipos e a chave residual de `outro`. A tela tem a mesma regra em
`web/src/assinaturaDoNome.ts`; `api/tests/assinatura_do_nome.json` é lida pelos dois testes.
"""

import re
from collections.abc import Iterable

from api.comparador import normalizar
from api.numero import singular

PALAVRAS_VAZIAS = frozenset({"de", "da", "do", "das", "dos", "com", "um", "uma"})
_PALAVRA = re.compile(r"[^\W_]+(?:-[^\W_]+)*")


def _singular_estavel(palavra: str) -> str:
    while (s := normalizar(singular(palavra))) != palavra:
        palavra = s
    return palavra


def _formas_da_cor(cor: str) -> set[str]:
    """A cor e o feminino ("vermelho" e "vermelha"); o plural sai no singular."""
    base = _singular_estavel(normalizar(cor))
    return {base, base[:-1] + "a"} if base.endswith("o") else {base}


def assinatura(nome: str, cores: Iterable[str] = ()) -> str:
    palavras = [
        _singular_estavel(p)
        for p in _PALAVRA.findall(normalizar(nome))
        if p not in PALAVRAS_VAZIAS
    ]
    cor = set().union(*(_formas_da_cor(c) for c in cores))
    # Nome que é só a cor ("vermelho") fica como está.
    sem_cor = [p for p in palavras if p not in cor] or palavras
    return " ".join(sorted(set(sem_cor)))
