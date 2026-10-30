"""Papéis e permissões (E3): pacotes de permissões, negadas por padrão.

As permissões ficam na aplicação (um documento por uid), não no token.
"""

from collections.abc import Callable, Iterable
from typing import Literal, Protocol, get_args

Papel = Literal["consulta", "operador", "editor", "curador"]
PAPEIS: tuple[Papel, ...] = get_args(Papel)
Permissao = Literal[
    "decupagem.ver", "video.enviar", "decupagem.editar", "correcao.aprovar"
]

_CONSULTA: frozenset[Permissao] = frozenset({"decupagem.ver"})
_EDITOR: frozenset[Permissao] = _CONSULTA | frozenset({"decupagem.editar"})
PERMISSOES_DO_PAPEL: dict[Papel, frozenset[Permissao]] = {
    "consulta": _CONSULTA,
    "operador": _CONSULTA | frozenset({"video.enviar"}),
    "editor": _EDITOR,
    "curador": _EDITOR | frozenset({"correcao.aprovar"}),
}

# Conta sem documento de papéis: o comportamento da E0, para ninguém perder acesso.
PAPEIS_PADRAO: list[Papel] = ["consulta", "operador"]


def permissoes_de(papeis: Iterable[Papel]) -> set[Permissao]:
    return {p for papel in papeis for p in PERMISSOES_DO_PAPEL[papel]}


def papeis_efetivos(guardados: list[Papel] | None) -> list[Papel]:
    """Os papéis do documento, ou os padrões se a conta não tem documento."""
    return list(PAPEIS_PADRAO) if guardados is None else guardados


class RepositorioDePapeis(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def obter(self, uid: str) -> list[Papel] | None: ...

    def salvar(self, uid: str, papeis: list[Papel]) -> None: ...


class RepositorioDePapeisEmMemoria:
    def __init__(self) -> None:
        self._papeis: dict[str, list[Papel]] = {}

    def obter(self, uid: str) -> list[Papel] | None:
        return self._papeis.get(uid)

    def salvar(self, uid: str, papeis: list[Papel]) -> None:
        self._papeis[uid] = papeis


class ContaNaoEncontrada(Exception):
    """Nenhuma conta do Identity Platform com esse e-mail."""


def atribuir_papeis_main(
    argv: list[str],
    repositorio: RepositorioDePapeis,
    achar_uid: Callable[[str], str],
    imprimir: Callable[[str], None] = print,
) -> int:
    uso = f"uso: make atribuir-papeis EMAIL=<e-mail> PAPEIS=<{','.join(PAPEIS)}>"
    if len(argv) != 2:
        imprimir(uso)
        return 2
    email = argv[0].strip()
    pedidos = sorted({p.strip() for p in argv[1].split(",") if p.strip()})
    desconhecidos = [p for p in pedidos if p not in PAPEIS]
    if not email or not pedidos or desconhecidos:
        if desconhecidos:
            imprimir(f"papel desconhecido: {', '.join(desconhecidos)}. {uso}")
        else:
            imprimir(uso)
        return 2
    try:
        uid = achar_uid(email)
    except ContaNaoEncontrada:
        imprimir(f"conta não encontrada: {email}")
        return 2
    papeis: list[Papel] = [p for p in PAPEIS if p in pedidos]
    repositorio.salvar(uid, papeis)
    imprimir(f"{email} (uid {uid}): {', '.join(papeis)}")
    return 0
