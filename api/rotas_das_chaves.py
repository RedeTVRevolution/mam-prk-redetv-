"""Chaves de API pela API (E8): emitir, listar e revogar em `/v1/admin/chaves`.

Reusa o domínio de `api.chaves`. O repositório guarda só o HMAC: a lista nunca o
devolve, e a chave em texto sai uma única vez, na resposta da emissão. A auditoria
registra o sistema, o id e os escopos, nunca a chave.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from api.auditoria import Acao, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Escopo, Usuario
from api.chaves import (
    LimiteDeChavesAtivas,
    Mac,
    RegistroDeChave,
    RepositorioDeChaves,
    emitir_chave,
    revogar_chave,
)
from api.jobs import ServicoIndisponivel, _confere_permissao

SISTEMA_MAXIMO = 100


class ChaveIndisponivel:
    """Sem repositório de chaves ou chave MAC configurados: tudo vira 503."""

    def listar(self) -> list[RegistroDeChave]:
        raise ServicoIndisponivel

    def obter(self, chave_id: str) -> RegistroDeChave | None:
        raise ServicoIndisponivel

    def salvar(self, registro: RegistroDeChave) -> None:
        raise ServicoIndisponivel

    def listar_por_sistema(self, sistema: str) -> list[RegistroDeChave]:
        raise ServicoIndisponivel

    def salvar_nova(self, registro: RegistroDeChave, maximo_ativas: int) -> None:
        raise ServicoIndisponivel


class MacIndisponivel:
    @property
    def versao_atual(self) -> int:
        raise ServicoIndisponivel

    def calcular(self, versao: int, mensagem: bytes) -> bytes:
        raise ServicoIndisponivel

    def verificar(self, versao: int, mensagem: bytes, mac: bytes) -> bool:
        raise ServicoIndisponivel


class ChaveDaLista(BaseModel):
    """O registro sem o HMAC nem a versão da chave MAC."""

    id: str
    sistema: str
    escopos: list[Escopo]
    criada_em: datetime
    revogada_em: datetime | None


class NovaChave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sistema: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=SISTEMA_MAXIMO
        ),
    ]
    escopos: Annotated[list[Escopo], Field(min_length=1)]


class ChaveEmitidaNaResposta(ChaveDaLista):
    # A única vez em que a chave em texto sai da API.
    chave: str


def _da_lista(registro: RegistroDeChave) -> ChaveDaLista:
    return ChaveDaLista(
        id=registro.id,
        sistema=registro.sistema,
        escopos=registro.escopos,
        criada_em=registro.criada_em,
        revogada_em=registro.revogada_em,
    )


def _exige_gerir(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `chaves.gerir`; chave de sistema não gere chaves."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não gere chaves")
    _confere_permissao(request, chamador, "chaves.gerir")
    return chamador


def criar_rotas_das_chaves(
    repositorio: RepositorioDeChaves,
    mac: Mac,
    auditoria: RepositorioDeAuditoria,
    relogio: Callable[[], datetime],
) -> APIRouter:
    rotas = APIRouter(prefix="/admin/chaves")

    def registrar(autor: Usuario, acao: Acao, registro: RegistroDeChave) -> None:
        auditoria.acrescentar(
            RegistroDeAuditoria(
                id=uuid.uuid4().hex,
                quando=relogio(),
                uid=autor.uid,
                email=autor.email,
                acao=acao,
                alvo_tipo="chave",
                alvo_id=registro.id,
                alvo_nome=registro.sistema,
                detalhes={"escopos": registro.escopos},
            )
        )

    @rotas.get("")
    def listar(
        _pessoa: Annotated[Usuario, Depends(_exige_gerir)],
    ) -> list[ChaveDaLista]:
        return [_da_lista(r) for r in repositorio.listar()]

    @rotas.post("", status_code=201)
    def emitir(
        pedido: NovaChave, pessoa: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> ChaveEmitidaNaResposta:
        try:
            emitida = emitir_chave(
                pedido.sistema, pedido.escopos, mac, repositorio, relogio()
            )
        except LimiteDeChavesAtivas as erro:
            raise HTTPException(409, str(erro)) from None
        except ValueError as erro:
            raise HTTPException(422, str(erro)) from None
        try:
            registrar(pessoa, "chave.emitida", emitida.registro)
        except Exception:
            # Sem registro, a chave não sai: ninguém a viu, então ela é revogada.
            revogar_chave(emitida.registro.id, repositorio, relogio())
            raise
        return ChaveEmitidaNaResposta(
            **_da_lista(emitida.registro).model_dump(), chave=emitida.chave
        )

    @rotas.post("/{chave_id}/revogar")
    def revogar(
        chave_id: str, pessoa: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> ChaveDaLista:
        antes = repositorio.obter(chave_id)
        if antes is None:
            raise HTTPException(404, "Chave não encontrada")
        if not antes.ativa:
            return _da_lista(antes)
        depois = revogar_chave(chave_id, repositorio, relogio())
        try:
            registrar(pessoa, "chave.revogada", depois)
        except Exception:
            repositorio.salvar(antes)
            raise
        return _da_lista(depois)

    return rotas
