"""Singular e plural em português, só pelas regras simples (#405): a busca trata
"microfone" e "microfones" como a mesma palavra, sem depender do índice."""

import re
from collections.abc import Callable, Iterable
from functools import lru_cache

from api.texto import normalizar

# Com e sem acento, para valer também o que se digita sem eles ("pais" é de pai, "país" fica).
_INVARIAVEIS = {
    "mais", "menos", "seis", "dois", "três", "tres", "cais", "deus", "país",
    "lápis", "lapis", "ônibus", "onibus", "tênis", "tenis", "vírus", "virus",
    "atlas", "pires", "simples", "oásis", "oasis", "tórax", "torax",
}  # fmt: skip
# Plurais que as regras erram, com o singular certo.
_IRREGULARES = {
    "mães": "mãe", "maes": "mãe", "reis": "rei", "leis": "lei", "bois": "boi",
    "pais": "pai", "heróis": "herói", "herois": "herói", "meses": "mês",
    "países": "país", "paises": "país", "gases": "gás",
    "árvores": "árvore", "arvores": "árvore",
}  # fmt: skip
_VOGAL_R = r"[aeiouáéíóúâêôàãõ]r$"
_REGRAS = (
    ("ões", "ão"), ("ães", "ão"), ("ãos", "ão"), ("oes", "ao"), ("ns", "m"),
    ("éis", "el"), ("eis", "el"), ("óis", "ol"), ("ois", "ol"),
    ("ais", "al"), ("uis", "ul"), ("zes", "z"), ("s", ""),
)  # fmt: skip


def singular(palavra: str) -> str:
    """O singular pelas regras simples; palavra curta ou sem plural fica como está."""
    p = palavra.casefold()
    if len(p) <= 3 or p in _INVARIAVEIS:
        return p
    if p in _IRREGULARES:
        return _IRREGULARES[p]
    if p.endswith("res"):
        # Depois de vogal o "-es" cai (flores, mulheres, bares); depois de consoante o "-s" (padres, torres).
        return p[:-2] if re.search(_VOGAL_R, p[:-2]) else p[:-1]
    for fim, troca in _REGRAS:
        if p.endswith(fim):
            return p[: -len(fim)] + troca
    return p


def _plurais(s: str) -> set[str]:
    irregulares = {p for p, sing in _IRREGULARES.items() if sing == s}
    if irregulares or s in _INVARIAVEIS:
        return irregulares
    if s.endswith("ão"):
        base = s[:-2]
        return {base + "ões", base + "ães", base + "ãos"}
    if s.endswith("ao"):
        return {s[:-2] + "oes"}
    if s.endswith("el"):
        return {s[:-2] + "éis"}
    if s.endswith("ol"):
        return {s[:-2] + "óis"}
    if s.endswith("l"):
        return {s[:-1] + "is"}
    if s.endswith("m"):
        return {s[:-1] + "ns"}
    if s.endswith(("r", "z")):
        return {s + "es"}
    if s.endswith("s"):
        return set()
    return {s + "s"}


# A busca compara sem acento: as tabelas e as regras abaixo valem para a palavra já normalizada,
# e assim "pães" e "paes" dão as mesmas formas.
_IRREGULARES_SEM_ACENTO = {
    normalizar(p): normalizar(s) for p, s in _IRREGULARES.items()
}
_INVARIAVEIS_SEM_ACENTO = {normalizar(p) for p in _INVARIAVEIS}


def raizes(palavra: str) -> frozenset[str]:
    """Os singulares possíveis da palavra sem acento: "pais" é de pai e de país."""
    return _raizes(normalizar(palavra))


@lru_cache(maxsize=8192)
def _raizes(n: str) -> frozenset[str]:
    if n in _IRREGULARES_SEM_ACENTO:
        achadas = {_IRREGULARES_SEM_ACENTO[n]}
    elif len(n) >= 4 and n.endswith("aes"):
        achadas = {n[:-3] + "ao"}  # pães, cães, alemães; "mães" é irregular
    else:
        achadas = {singular(n)}
    if n in _INVARIAVEIS_SEM_ACENTO:
        achadas.add(n)
    return frozenset(achadas)


def _plurais_sem_acento(raiz: str) -> set[str]:
    irregulares = {p for p, s in _IRREGULARES_SEM_ACENTO.items() if s == raiz}
    if irregulares or raiz in _INVARIAVEIS_SEM_ACENTO:
        return irregulares
    if raiz.endswith("ao"):
        # Sem "-aes" que é de outra palavra: "mao" não acha "maes" (de mãe).
        return {
            raiz[:-2] + fim for fim in ("oes", "aes", "aos")
        } - _IRREGULARES_SEM_ACENTO.keys()
    return {normalizar(p) for p in _plurais(raiz)}


def formas(palavra: str) -> set[str]:
    """Sem acento: a palavra, os singulares dela e os plurais deles, o que se manda ao
    índice para achar o registro gravado em qualquer número."""
    achadas = raizes(palavra)
    return {normalizar(palavra), *achadas}.union(*map(_plurais_sem_acento, achadas))


def mesma_palavra(a: str, b: str) -> bool:
    """Iguais no número, sem acento nem maiúscula."""
    return not raizes(a).isdisjoint(raizes(b))


def em_grupo(palavra: str, outras: Iterable[str]) -> str:
    """A palavra e as `outras` num grupo OR, como o índice lê; sozinha se não há outras."""
    grupo = [palavra, *sorted(outras)]
    return f"({' OR '.join(grupo)})" if len(grupo) > 1 else palavra


def com_as_formas(
    texto: str, variantes: Callable[[str], set[str]] = lambda _: set()
) -> str:
    """Formas sem acento em grupos OR, com as `variantes` de grafia da palavra; palavras
    repetidas e pontuação ficam de fora."""
    saida: list[str] = []
    vistas: set[str] = set()
    for palavra in re.findall(r"\w+", texto):
        digitada = normalizar(palavra)
        if digitada in vistas:
            continue
        vistas.add(digitada)
        saida.append(
            em_grupo(digitada, (formas(digitada) | variantes(digitada)) - {digitada})
        )
    return " ".join(saida)
