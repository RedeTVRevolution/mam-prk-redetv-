"""Usuários e papéis pela API (E8): criar conta, reenviar o link, trocar papéis, desativar.

O Identity Platform fica atrás da porta `ContasDeUsuario`; os testes usam o dublê em
memória. Os papéis e a marca `desativada` ficam no documento de papéis (`api.papeis`),
que a API lê a cada requisição: desativar vale na hora, mesmo com um ID token válido.
A conta nunca é apagada, porque as correções guardam o autor. Cada ação deixa um
registro na auditoria.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StringConstraints,
)

from api.auditoria import Acao, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.jobs import ServicoIndisponivel, _confere_permissao
from api.papeis import (
    PAPEIS,
    Papel,
    RepositorioDePapeis,
    papeis_do_usuario,
    papeis_efetivos,
)

NOME_MAXIMO = 200


class ContaDoIdentityPlatform(BaseModel):
    model_config = ConfigDict(frozen=True)

    uid: str
    email: str
    nome: str = ""
    email_verificado: bool = False
    criada_em: AwareDatetime | None = None
    ultimo_acesso: AwareDatetime | None = None
    bloqueada: bool = False


class EmailJaCadastrado(Exception):
    """Já existe uma conta com esse e-mail."""


class ContasDeUsuario(Protocol):
    """Porta para o Identity Platform; os testes usam uma versão em memória."""

    def listar(self) -> list[ContaDoIdentityPlatform]: ...

    def obter(self, uid: str) -> ContaDoIdentityPlatform | None: ...

    def criar(self, email: str, nome: str) -> ContaDoIdentityPlatform:
        """Cria a conta local com e-mail verificado e senha descartável.
        Levanta `EmailJaCadastrado`."""
        ...

    def enviar_link_de_senha(self, email: str) -> None: ...

    def bloquear(self, uid: str, bloqueada: bool) -> None:
        """Bloqueia (ou libera) o login; bloquear também revoga os tokens de atualização."""
        ...


class ContasDeUsuarioEmMemoria:
    def __init__(self, contas: list[ContaDoIdentityPlatform] | None = None) -> None:
        self._contas = {c.uid: c for c in contas or []}
        self.links_enviados: list[str] = []
        self.sessoes_revogadas: list[str] = []

    def listar(self) -> list[ContaDoIdentityPlatform]:
        return list(self._contas.values())

    def obter(self, uid: str) -> ContaDoIdentityPlatform | None:
        return self._contas.get(uid)

    def criar(self, email: str, nome: str) -> ContaDoIdentityPlatform:
        if any(c.email.lower() == email.lower() for c in self._contas.values()):
            raise EmailJaCadastrado(email)
        conta = ContaDoIdentityPlatform(
            uid=f"uid-{len(self._contas) + 1}",
            email=email,
            nome=nome,
            email_verificado=True,
        )
        self._contas[conta.uid] = conta
        return conta

    def enviar_link_de_senha(self, email: str) -> None:
        self.links_enviados.append(email)

    def bloquear(self, uid: str, bloqueada: bool) -> None:
        self._contas[uid] = self._contas[uid].model_copy(
            update={"bloqueada": bloqueada}
        )
        if bloqueada:
            self.sessoes_revogadas.append(uid)


class ContasIndisponiveis:
    """Sem Identity Platform configurado (fora do Cloud Run): tudo vira 503."""

    def listar(self) -> list[ContaDoIdentityPlatform]:
        raise ServicoIndisponivel

    def obter(self, uid: str) -> ContaDoIdentityPlatform | None:
        raise ServicoIndisponivel

    def criar(self, email: str, nome: str) -> ContaDoIdentityPlatform:
        raise ServicoIndisponivel

    def enviar_link_de_senha(self, email: str) -> None:
        raise ServicoIndisponivel

    def bloquear(self, uid: str, bloqueada: bool) -> None:
        raise ServicoIndisponivel


class UsuarioDaLista(BaseModel):
    uid: str
    email: str
    nome: str
    papeis: list[Papel]
    criada_em: AwareDatetime | None
    ultimo_acesso: AwareDatetime | None
    situacao: Literal["ativa", "desativada"]


def _em_ordem(papeis: list[Papel]) -> list[Papel]:
    return [p for p in PAPEIS if p in papeis]


# Sem repetição e na ordem de `PAPEIS`.
PapeisPedidos = Annotated[list[Papel], AfterValidator(_em_ordem)]


class NovoUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[
        str, StringConstraints(strip_whitespace=True, pattern=r"^[^@\s]+@[^@\s]+$")
    ]
    nome: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=NOME_MAXIMO),
    ]
    papeis: PapeisPedidos


class PapeisDoUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    papeis: PapeisPedidos


def _exige_gerir(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `usuarios.gerir`; chave de sistema não gere usuários."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não gere usuários")
    _confere_permissao(request, chamador, "usuarios.gerir")
    return chamador


def criar_rotas_dos_usuarios(
    contas: ContasDeUsuario,
    papeis: RepositorioDePapeis,
    auditoria: RepositorioDeAuditoria,
    admins: Callable[[], frozenset[str]],
    relogio: Callable[[], datetime],
) -> APIRouter:
    rotas = APIRouter(prefix="/admin/usuarios")

    def efetivos(
        conta: ContaDoIdentityPlatform, guardados: list[Papel] | None
    ) -> list[Papel]:
        return papeis_do_usuario(
            guardados, conta.email, conta.email_verificado, admins()
        )

    def da_lista(conta: ContaDoIdentityPlatform) -> UsuarioDaLista:
        desativada = conta.bloqueada or papeis.desativada(conta.uid)
        return UsuarioDaLista(
            uid=conta.uid,
            email=conta.email,
            nome=conta.nome,
            papeis=efetivos(conta, papeis.obter(conta.uid)),
            criada_em=conta.criada_em,
            ultimo_acesso=conta.ultimo_acesso,
            situacao="desativada" if desativada else "ativa",
        )

    def achar(uid: str) -> ContaDoIdentityPlatform:
        conta = contas.obter(uid)
        if conta is None:
            raise HTTPException(404, "Conta não encontrada")
        return conta

    def registrar(
        autor: Usuario,
        acao: Acao,
        conta: ContaDoIdentityPlatform,
        detalhes: dict[str, object] | None = None,
    ) -> None:
        auditoria.acrescentar(
            RegistroDeAuditoria(
                id=uuid.uuid4().hex,
                quando=relogio(),
                uid=autor.uid,
                email=autor.email,
                acao=acao,
                alvo_tipo="usuario",
                alvo_id=conta.uid,
                alvo_nome=conta.email,
                detalhes=detalhes or {},
            )
        )

    @rotas.get("")
    def listar(
        _pessoa: Annotated[Usuario, Depends(_exige_gerir)],
    ) -> list[UsuarioDaLista]:
        return sorted(
            (da_lista(c) for c in contas.listar()), key=lambda u: u.email.lower()
        )

    @rotas.post("", status_code=201)
    def criar(
        pedido: NovoUsuario, pessoa: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> UsuarioDaLista:
        try:
            conta = contas.criar(pedido.email, pedido.nome)
        except EmailJaCadastrado:
            raise HTTPException(409, "Já existe uma conta com esse e-mail") from None
        papeis.salvar(conta.uid, pedido.papeis)
        # O registro antes do link: se o envio falha, a conta já tem rastro e o
        # link pode ser reenviado.
        registrar(pessoa, "conta.criada", conta, {"papeis": pedido.papeis})
        contas.enviar_link_de_senha(conta.email)
        return da_lista(conta)

    @rotas.post("/{uid}/link-de-senha")
    def reenviar_link(
        uid: str, pessoa: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> dict[str, bool]:
        conta = achar(uid)
        contas.enviar_link_de_senha(conta.email)
        registrar(pessoa, "conta.link_reenviado", conta)
        return {"enviado": True}

    @rotas.put("/{uid}/papeis")
    def trocar_papeis(
        uid: str,
        pedido: PapeisDoUsuario,
        pessoa: Annotated[Usuario, Depends(_exige_gerir)],
    ) -> UsuarioDaLista:
        conta = achar(uid)
        guardados = papeis.obter(uid)
        # Antes e depois são os papéis efetivos: o administrador de emergência
        # continua Administrador mesmo sem o papel guardado.
        antes = efetivos(conta, guardados)
        depois = efetivos(conta, pedido.papeis)
        if (
            uid == pessoa.uid
            and "administrador" in antes
            and "administrador" not in depois
        ):
            raise HTTPException(
                409, "Você não pode tirar de si mesmo o papel de Administrador"
            )
        papeis.salvar(uid, pedido.papeis)
        try:
            registrar(
                pessoa, "papeis.alterados", conta, {"antes": antes, "depois": depois}
            )
        except Exception:
            papeis.salvar(uid, papeis_efetivos(guardados))
            raise
        return da_lista(conta)

    @rotas.post("/{uid}/desativar")
    def desativar(
        uid: str, pessoa: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> UsuarioDaLista:
        if uid == pessoa.uid:
            raise HTTPException(409, "Você não pode desativar a própria conta")
        conta = achar(uid)
        # A marca primeiro: é ela que corta o acesso na hora. Sem registro, a marca
        # sai. O bloqueio no Identity Platform e a revogação dos tokens vêm por
        # último; se falham, o corte já vale e o pedido pode ser repetido.
        papeis.marcar_desativada(uid, True)
        try:
            registrar(pessoa, "conta.desativada", conta)
        except Exception:
            papeis.marcar_desativada(uid, False)
            raise
        contas.bloquear(uid, True)
        return da_lista(achar(uid))

    @rotas.post("/{uid}/reativar")
    def reativar(
        uid: str, pessoa: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> UsuarioDaLista:
        conta = achar(uid)
        contas.bloquear(uid, False)
        papeis.marcar_desativada(uid, False)
        try:
            registrar(pessoa, "conta.reativada", conta)
        except Exception:
            papeis.marcar_desativada(uid, True)
            contas.bloquear(uid, True)
            raise
        return da_lista(achar(uid))

    return rotas
