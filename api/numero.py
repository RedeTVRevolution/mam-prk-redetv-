"""Singular e plural em português, só pelas regras simples (#405): a busca trata
"microfone" e "microfones" como a mesma palavra, sem depender do índice."""

import re

from api.comparador import normalizar

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
}  # fmt: skip
_REGRAS = (
    ("ões", "ão"), ("ães", "ão"), ("ãos", "ão"), ("oes", "ao"), ("ns", "m"),
    ("éis", "el"), ("eis", "el"), ("óis", "ol"), ("ois", "ol"),
    ("ais", "al"), ("uis", "ul"), ("res", "r"), ("zes", "z"), ("s", ""),
)  # fmt: skip


def singular(palavra: str) -> str:
    """O singular pelas regras simples; palavra curta ou sem plural fica como está."""
    p = palavra.casefold()
    if len(p) <= 3 or p in _INVARIAVEIS:
        return p
    if p in _IRREGULARES:
        return _IRREGULARES[p]
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


def formas(palavra: str) -> set[str]:
    """A palavra, o singular dela e os plurais desse singular: o que se manda ao índice
    para achar o registro gravado em qualquer número."""
    p = palavra.casefold()
    s = singular(p)
    return {p, s} | _plurais(s)


def mesma_palavra(a: str, b: str) -> bool:
    """Iguais no número, sem acento nem maiúscula."""
    return normalizar(singular(a)) == normalizar(singular(b))


def com_as_formas(texto: str) -> str:
    """Formas normalizadas em grupos OR; palavras repetidas e pontuação ficam de fora."""
    saida: list[str] = []
    vistas: set[str] = set()
    for palavra in re.findall(r"\w+", texto):
        digitada = normalizar(palavra)
        if digitada in vistas:
            continue
        vistas.add(digitada)
        outras = {normalizar(forma) for forma in formas(palavra)} - {digitada}
        grupo = [digitada, *sorted(outras)]
        saida.append(f"({' OR '.join(grupo)})" if outras else digitada)
    return " ".join(saida)
