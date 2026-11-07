"""Aprovação opcional de Curador (E3): quais tipos de correção exigem aprovação.

A lista fica num documento do Firestore e o Administrador a muda pela aba "Regras
de aprovação" (`/v1/admin/aprovacao`). Vazia por padrão: nada exige aprovação. A
mudança vale na hora para as correções novas; as pendentes continuam pendentes.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from api.auditoria import RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.correcoes import CORRIGIVEIS, RepositorioDeAprovacao, rotulos_dos_tipos
from api.jobs import _confere_permissao
from api.texto_como_dado import Linha


class RegraDeAprovacao(BaseModel):
    tipo: str
    # O nome do tipo para quem lê, o mesmo do histórico de correções.
    nome: str
    exige_aprovacao: bool


class MudancaDaRegra(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: Annotated[str, Linha(60, min_length=1)]
    exige_aprovacao: bool


def _nomes() -> dict[str, str]:
    return {o.valor: o.rotulo for o in rotulos_dos_tipos()}


def _regras(exigem: frozenset[str]) -> list[RegraDeAprovacao]:
    nomes = _nomes()
    return [
        RegraDeAprovacao(tipo=t, nome=nomes.get(t, t), exige_aprovacao=t in exigem)
        for t in CORRIGIVEIS
    ]


def _exige_definir(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `aprovacao.definir`; chave de sistema não muda regras."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não muda as regras de aprovação")
    _confere_permissao(request, chamador, "aprovacao.definir")
    return chamador


def criar_rotas_da_aprovacao(
    repositorio: RepositorioDeAprovacao,
    auditoria: RepositorioDeAuditoria,
    relogio: Callable[[], datetime],
) -> APIRouter:
    rotas = APIRouter(prefix="/admin/aprovacao")

    @rotas.get("")
    def listar(
        _pessoa: Annotated[Usuario, Depends(_exige_definir)],
    ) -> list[RegraDeAprovacao]:
        return _regras(repositorio.tipos())

    @rotas.put("")
    def mudar(
        pedido: MudancaDaRegra, pessoa: Annotated[Usuario, Depends(_exige_definir)]
    ) -> list[RegraDeAprovacao]:
        if pedido.tipo not in CORRIGIVEIS:
            raise HTTPException(422, f"Tipo de correção desconhecido: {pedido.tipo}")
        antes = repositorio.tipos()
        if (pedido.tipo in antes) == pedido.exige_aprovacao:
            return _regras(antes)
        repositorio.mudar(pedido.tipo, pedido.exige_aprovacao)
        try:
            auditoria.acrescentar(
                RegistroDeAuditoria(
                    id=uuid.uuid4().hex,
                    quando=relogio(),
                    uid=pessoa.uid,
                    email=pessoa.email,
                    acao="aprovacao.alterada",
                    alvo_tipo="tipo_de_correcao",
                    alvo_id=pedido.tipo,
                    alvo_nome=_nomes().get(pedido.tipo, pedido.tipo),
                    detalhes={
                        "antes": pedido.tipo in antes,
                        "depois": pedido.exige_aprovacao,
                    },
                )
            )
        except Exception:
            # Sem registro, a mudança não fica.
            repositorio.mudar(pedido.tipo, not pedido.exige_aprovacao)
            raise
        return _regras(repositorio.tipos())

    return rotas
