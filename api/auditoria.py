"""Registro de auditoria (E8): o que a administração fez, só de acréscimo.

A interface tem acrescentar e consultar; nada altera nem apaga um registro.
"""

import itertools
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth import ChamadorAutenticado, Usuario
from api.jobs import CursorInvalido, _confere_permissao

# Cada ticket que grava uma ação nova a acrescenta a esta lista.
Acao = Literal[
    "conta.criada",
    "conta.link_reenviado",
    "conta.desativada",
    "conta.reativada",
    "papeis.alterados",
    "chave.emitida",
    "chave.revogada",
    "item.para_lixeira",
    "item.restaurado",
    "item.purgado",
    "video.reprocessado",
]
ACOES: tuple[Acao, ...] = get_args(Acao)

LIMITE_PADRAO = 50
LIMITE_MAXIMO = 200


class RegistroDeAuditoria(BaseModel):
    id: str
    quando: datetime
    # Quem fez: a pessoa (uid e e-mail) ou o nome do sistema.
    uid: str | None = None
    email: str | None = None
    sistema: str | None = None
    acao: Acao
    # O alvo: tipo, id e um nome legível (e-mail da conta, nome do arquivo...).
    alvo_tipo: str
    alvo_id: str
    alvo_nome: str
    motivo: str | None = None
    # Antes e depois (papéis), números do impacto (lixeira, purga), etapa (reprocessamento).
    detalhes: dict[str, Any] = {}


@dataclass(frozen=True)
class FiltroDeAuditoria:
    pessoa: str | None = None  # uid ou e-mail
    alvo_id: str | None = None
    acao: Acao | None = None
    de: datetime | None = None  # incluído
    ate: datetime | None = None  # incluído
    limite: int | None = None
    cursor: str | None = None  # id do último registro da página anterior


@dataclass(frozen=True)
class PaginaDeAuditoria:
    registros: list[RegistroDeAuditoria]
    proximo_cursor: str | None = None


def campo_da_pessoa(pessoa: str) -> tuple[str, str]:
    """O campo e o valor a comparar: e-mail (sem maiúsculas) se tem `@`, senão uid."""
    texto = pessoa.strip()
    return ("email", texto.lower()) if "@" in texto else ("uid", texto)


def casa_com_o_filtro(registro: RegistroDeAuditoria, filtro: FiltroDeAuditoria) -> bool:
    if filtro.pessoa is not None:
        campo, valor = campo_da_pessoa(filtro.pessoa)
        guardado = getattr(registro, campo)
        if (guardado.lower() if campo == "email" and guardado else guardado) != valor:
            return False
    if filtro.alvo_id is not None and registro.alvo_id != filtro.alvo_id:
        return False
    if filtro.acao is not None and registro.acao != filtro.acao:
        return False
    if filtro.de is not None and registro.quando < filtro.de:
        return False
    return filtro.ate is None or registro.quando <= filtro.ate


class RepositorioDeAuditoria(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def acrescentar(self, registro: RegistroDeAuditoria) -> None: ...

    def consultar(self, filtro: FiltroDeAuditoria) -> PaginaDeAuditoria: ...


class RepositorioDeAuditoriaEmMemoria:
    def __init__(self) -> None:
        self._registros: dict[str, RegistroDeAuditoria] = {}

    def acrescentar(self, registro: RegistroDeAuditoria) -> None:
        if registro.id in self._registros:
            raise ValueError(f"registro já existe: {registro.id}")
        self._registros[registro.id] = registro

    def consultar(self, filtro: FiltroDeAuditoria) -> PaginaDeAuditoria:
        """Mais recente primeiro (desempate pelo id, na mesma direção).
        Levanta `CursorInvalido` se o cursor não existe."""
        ordenados = sorted(
            self._registros.values(), key=lambda r: (r.quando, r.id), reverse=True
        )
        if filtro.cursor is not None:
            if filtro.cursor not in self._registros:
                raise CursorInvalido
            ids = [r.id for r in ordenados]
            ordenados = ordenados[ids.index(filtro.cursor) + 1 :]
        achados = (r for r in ordenados if casa_com_o_filtro(r, filtro))
        return pagina_de(achados, filtro.limite)


def pagina_de(registros: Any, limite: int | None) -> PaginaDeAuditoria:
    """Corta os registros já filtrados e em ordem; só lê um além do limite."""
    if limite is None:
        return PaginaDeAuditoria(list(registros))
    lidos = list(itertools.islice(registros, limite + 1))
    if len(lidos) <= limite:
        return PaginaDeAuditoria(lidos)
    pagina = lidos[:limite]
    return PaginaDeAuditoria(pagina, pagina[-1].id)


def _exige_ver(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `auditoria.ver`; chave de sistema não consulta."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não consulta a auditoria")
    _confere_permissao(request, chamador, "auditoria.ver")
    return chamador


def criar_rotas_da_auditoria(repositorio: RepositorioDeAuditoria) -> APIRouter:
    rotas = APIRouter(prefix="/admin/auditoria")

    @rotas.get("")
    def listar(
        _pessoa: Annotated[Usuario, Depends(_exige_ver)],
        pessoa: str | None = None,
        alvo: str | None = None,
        acao: Acao | None = None,
        de: datetime | None = None,
        ate: datetime | None = None,
        limite: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = LIMITE_PADRAO,
        cursor: str | None = None,
    ) -> JSONResponse:
        filtro = FiltroDeAuditoria(
            pessoa=pessoa,
            alvo_id=alvo,
            acao=acao,
            de=de,
            ate=ate,
            limite=limite,
            cursor=cursor,
        )
        try:
            pagina = repositorio.consultar(filtro)
        except CursorInvalido:
            raise HTTPException(422, "Cursor inválido") from None
        corpo = [r.model_dump(mode="json") for r in pagina.registros]
        cabecalhos = (
            {"X-Proximo-Cursor": pagina.proximo_cursor} if pagina.proximo_cursor else {}
        )
        return JSONResponse(corpo, headers=cabecalhos)

    return rotas
