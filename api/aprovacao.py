"""Aprovação opcional de Curador (E3): quais tipos de correção exigem aprovação.

A lista fica num documento do Firestore e o Administrador a muda pela aba "Regras
de aprovação" (`/v1/admin/aprovacao`). Vazia por padrão: nada exige aprovação. A
mudança vale na hora para as correções novas; as pendentes continuam pendentes.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from api.auditoria import RepositorioDeAuditoria, registro_de_auditoria
from api.auth import Usuario
from api.correcoes import CORRIGIVEIS, RepositorioDeAprovacao, rotulos_dos_tipos
from api.permissoes import exige
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


def criar_rotas_da_aprovacao(
    repositorio: RepositorioDeAprovacao,
    auditoria: RepositorioDeAuditoria,
    relogio: Callable[[], datetime],
) -> APIRouter:
    rotas = APIRouter(prefix="/admin/aprovacao")

    @rotas.get("")
    def listar(
        _pessoa: Annotated[
            Usuario,
            Depends(
                exige(
                    "aprovacao.definir",
                    "Chave de sistema não muda as regras de aprovação",
                )
            ),
        ],
    ) -> list[RegraDeAprovacao]:
        return _regras(repositorio.tipos())

    @rotas.put("")
    def mudar(
        pedido: MudancaDaRegra,
        pessoa: Annotated[
            Usuario,
            Depends(
                exige(
                    "aprovacao.definir",
                    "Chave de sistema não muda as regras de aprovação",
                )
            ),
        ],
    ) -> list[RegraDeAprovacao]:
        if pedido.tipo not in CORRIGIVEIS:
            raise HTTPException(422, f"Tipo de correção desconhecido: {pedido.tipo}")
        antes = repositorio.tipos()
        if (pedido.tipo in antes) == pedido.exige_aprovacao:
            return _regras(antes)
        repositorio.mudar(pedido.tipo, pedido.exige_aprovacao)
        try:
            auditoria.acrescentar(
                registro_de_auditoria(
                    quando=relogio(),
                    quem=pessoa,
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
