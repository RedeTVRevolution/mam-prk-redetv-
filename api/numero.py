"""Singular e plural em português, só pelas regras simples (#405): a busca trata
"microfone" e "microfones" como a mesma palavra, sem depender do índice."""

import unicodedata


def _sem_acento(palavra: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", palavra)
        if not unicodedata.combining(c)
    ).casefold()


def singular(palavra: str) -> str:
    """O singular pelas regras simples; palavra curta ou sem plural fica como está."""
    p = palavra.casefold()
    if len(p) <= 3:
        return p
    for fim, troca in (("ões", "ão"), ("ães", "ão"), ("ãos", "ão"), ("ns", "m")):
        if p.endswith(fim):
            return p[: -len(fim)] + troca
    if p.endswith(("res", "zes")):
        return p[:-2]
    if p.endswith(("ais", "eis", "uis", "óis")):
        return p[:-2] + "l"
    if p.endswith("s"):
        return p[:-1]
    return p


def _plurais(singular: str) -> set[str]:
    if singular.endswith("ão"):
        base = singular[:-2]
        return {base + "ões", base + "ães", base + "ãos"}
    if singular.endswith("l"):
        return {singular[:-1] + "is"}
    if singular.endswith("m"):
        return {singular[:-1] + "ns"}
    if singular.endswith(("r", "z")):
        return {singular + "es"}
    if singular.endswith("s"):
        return set()
    return {singular + "s"}


def formas(palavra: str) -> set[str]:
    """A palavra, o singular dela e os plurais desse singular: o que se manda ao índice
    para achar o registro gravado em qualquer número."""
    p = palavra.casefold()
    s = singular(p)
    return {p, s} | _plurais(s)


def mesma_palavra(a: str, b: str) -> bool:
    """Iguais no número, sem acento nem maiúscula."""
    return _sem_acento(singular(a)) == _sem_acento(singular(b))


def com_as_formas(texto: str) -> str:
    """O texto com cada palavra seguida das outras formas dela, para o índice."""
    saida: list[str] = []
    vistas: set[str] = set()
    for palavra in texto.split():
        for forma in [palavra, *sorted(formas(palavra) - {palavra.casefold()})]:
            if forma.casefold() not in vistas:
                vistas.add(forma.casefold())
                saida.append(forma)
    return " ".join(saida)
