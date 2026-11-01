"""Papéis e permissões (E3): pacotes de permissões, negadas por padrão.

As permissões ficam na aplicação (um documento por uid), não no token.
"""

from collections.abc import Callable, Iterable
from typing import Literal, Protocol, get_args

Papel = Literal["consulta", "operador", "editor", "curador", "administrador"]
PAPEIS: tuple[Papel, ...] = get_args(Papel)
Permissao = Literal[
    "decupagem.ver",
    "video.enviar",
    "decupagem.editar",
    "correcao.aprovar",
    "auditoria.ver",
    "video.reprocessar",
]

_CONSULTA: frozenset[Permissao] = frozenset({"decupagem.ver"})
_EDITOR: frozenset[Permissao] = _CONSULTA | frozenset({"decupagem.editar"})
PERMISSOES_DO_PAPEL: dict[Papel, frozenset[Permissao]] = {
    "consulta": _CONSULTA,
    "operador": _CONSULTA | frozenset({"video.enviar", "video.reprocessar"}),
    "editor": _EDITOR,
    "curador": _EDITOR | frozenset({"correcao.aprovar"}),
    # Do próprio tipo, para uma permissão nova chegar ao Administrador sozinha.
    "administrador": frozenset(get_args(Permissao)),
}

# Conta sem documento de papéis: o comportamento da E0, para ninguém perder acesso.
PAPEIS_PADRAO: list[Papel] = ["consulta", "operador"]


def permissoes_de(papeis: Iterable[Papel]) -> set[Permissao]:
    return {p for papel in papeis for p in PERMISSOES_DO_PAPEL[papel]}


def papeis_efetivos(guardados: list[Papel] | None) -> list[Papel]:
    """Os papéis do documento, ou os padrões se a conta não tem documento."""
    return list(PAPEIS_PADRAO) if guardados is None else guardados


def admins_de(lista: str | None) -> frozenset[str]:
    """Os e-mails de `ADMINS_EMERGENCIA` (separados por vírgula), sem espaços nem maiúsculas."""
    emails = (e.strip().lower() for e in (lista or "").split(","))
    return frozenset(e for e in emails if e)


def papeis_do_usuario(
    guardados: list[Papel] | None,
    email: str,
    email_verificado: bool,
    admins: frozenset[str],
) -> list[Papel]:
    """Os papéis efetivos de uma pessoa. O Administrador é calculado a cada
    requisição para quem tem e-mail verificado em `ADMINS_EMERGENCIA`; nada é gravado."""
    efetivos = papeis_efetivos(guardados)
    admin = email_verificado and email.strip().lower() in admins
    if admin and "administrador" not in efetivos:
        efetivos = [*efetivos, "administrador"]
    return efetivos


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
