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
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
)

from api.auditoria import Acao, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.jobs import ServicoIndisponivel, _confere_permissao
from api.papeis import (
    PAPEIS,
    Papel,
    RepositorioDePapeis,
    papeis_do_usuario,
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

    def _falha(self) -> ServicoIndisponivel:
        return ServicoIndisponivel()

    def listar(self) -> list[ContaDoIdentityPlatform]:
        raise self._falha()

    def obter(self, uid: str) -> ContaDoIdentityPlatform | None:
        raise self._falha()

    def criar(self, email: str, nome: str) -> ContaDoIdentityPlatform:
        raise self._falha()

    def enviar_link_de_senha(self, email: str) -> None:
        raise self._falha()

    def bloquear(self, uid: str, bloqueada: bool) -> None:
        raise self._falha()


class UsuarioDaLista(BaseModel):
    uid: str
    email: str
    nome: str
    papeis: list[Papel]
    criada_em: AwareDatetime | None
    ultimo_acesso: AwareDatetime | None
    situacao: str  # "ativa" ou "desativada"


class NovoUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[
        str, StringConstraints(strip_whitespace=True, pattern=r"^[^@\s]+@[^@\s]+$")
    ]
    nome: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=NOME_MAXIMO),
    ]
    papeis: list[Papel]

    @field_validator("papeis")
    @classmethod
    def _sem_repeticao(cls, papeis: list[Papel]) -> list[Papel]:
        return _em_ordem(papeis)


class PapeisDoUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    papeis: list[Papel]

    @field_validator("papeis")
    @classmethod
    def _sem_repeticao(cls, papeis: list[Papel]) -> list[Papel]:
        return _em_ordem(papeis)


def _em_ordem(papeis: list[Papel]) -> list[Papel]:
    return [p for p in PAPEIS if p in papeis]


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

    def efetivos(conta: ContaDoIdentityPlatform) -> list[Papel]:
        return papeis_do_usuario(
            papeis.obter(conta.uid), conta.email, conta.email_verificado, admins()
        )

    def da_lista(conta: ContaDoIdentityPlatform) -> UsuarioDaLista:
        desativada = conta.bloqueada or papeis.desativada(conta.uid)
        return UsuarioDaLista(
            uid=conta.uid,
            email=conta.email,
            nome=conta.nome,
            papeis=efetivos(conta),
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
        contas.enviar_link_de_senha(conta.email)
        registrar(pessoa, "conta.criada", conta, {"papeis": pedido.papeis})
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
        antes = efetivos(conta)
        if (
            uid == pessoa.uid
            and "administrador" in antes
            and "administrador" not in pedido.papeis
        ):
            raise HTTPException(
                409, "Você não pode tirar de si mesmo o papel de Administrador"
            )
        papeis.salvar(uid, pedido.papeis)
        registrar(
            pessoa,
            "papeis.alterados",
            conta,
            {"antes": antes, "depois": pedido.papeis},
        )
        return da_lista(conta)

    @rotas.post("/{uid}/desativar")
    def desativar(
        uid: str, pessoa: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> UsuarioDaLista:
        if uid == pessoa.uid:
            raise HTTPException(409, "Você não pode desativar a própria conta")
        conta = achar(uid)
        # A marca primeiro: é ela que corta o acesso na hora; o bloqueio no
        # Identity Platform e a revogação dos tokens vêm em seguida.
        papeis.marcar_desativada(uid, True)
        contas.bloquear(uid, True)
        registrar(pessoa, "conta.desativada", conta)
        return da_lista(achar(uid))

    @rotas.post("/{uid}/reativar")
    def reativar(
        uid: str, pessoa: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> UsuarioDaLista:
        conta = achar(uid)
        contas.bloquear(uid, False)
        papeis.marcar_desativada(uid, False)
        registrar(pessoa, "conta.reativada", conta)
        return da_lista(achar(uid))

    return rotas
