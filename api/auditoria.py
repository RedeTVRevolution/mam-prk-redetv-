"""Registro de auditoria (E8): o que a administração fez, só de acréscimo.

A interface tem acrescentar e consultar; nada altera nem apaga um registro.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol, get_args

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, field_validator, model_validator

from api.auth import Sistema, Usuario
from api.modelo_do_job import CursorInvalido, um_alem_do_limite
from api.permissoes import exige
from api.texto_como_dado import LinhaDaConsulta

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
    "job.estado_corrigido",
    "video.aberto",
    "video.baixado",
    "decupagem.baixada",
    "pessoa.fundida",
    "pessoa.renomeada",
    "aprovacao.alterada",
    "painel.aberto",
    "painel.exportado",
    "programa.criado",
    "programa.alterado",
    "programa.apagado",
    "marca.criada",
    "marca.alterada",
    "marca.juntada",
    "video.editado",
]
ACOES: tuple[Acao, ...] = get_args(Acao)

LIMITE_PADRAO = 50
LIMITE_MAXIMO = 200


class RegistroDeAuditoria(BaseModel):
    id: str
    quando: AwareDatetime
    # Quem fez: a pessoa (uid e e-mail) ou o nome do sistema, nunca os dois.
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

    @field_validator("email")
    @classmethod
    def _email_sem_maiusculas(cls, email: str | None) -> str | None:
        # A busca por pessoa compara o e-mail sem maiúsculas.
        return email.lower() if email else email

    @model_validator(mode="after")
    def _pessoa_ou_sistema(self) -> "RegistroDeAuditoria":
        pessoa = self.uid is not None and self.email is not None
        so_parte = (self.uid is None) != (self.email is None)
        if so_parte or pessoa == (self.sistema is not None):
            raise ValueError("quem fez é a pessoa (uid e e-mail) ou o sistema")
        return self


def registro_de_auditoria(
    quem: Usuario | Sistema | str,
    quando: datetime,
    acao: Acao,
    alvo_tipo: str,
    alvo_id: str,
    alvo_nome: str,
    motivo: str | None = None,
    detalhes: dict[str, Any] | None = None,
) -> RegistroDeAuditoria:
    """O registro de uma ação: quem fez (pessoa ou sistema), o alvo e o `id` novo."""
    # Texto é o nome de um sistema sem chave (purga automática, comandos do `make`).
    de_quem = (
        {"uid": quem.uid, "email": quem.email}
        if isinstance(quem, Usuario)
        else {"sistema": quem if isinstance(quem, str) else quem.sistema}
    )
    return RegistroDeAuditoria(
        id=uuid.uuid4().hex,
        quando=quando,
        **de_quem,
        acao=acao,
        alvo_tipo=alvo_tipo,
        alvo_id=alvo_id,
        alvo_nome=alvo_nome,
        motivo=motivo,
        detalhes=detalhes or {},
    )


@dataclass(frozen=True)
class FiltroDeAuditoria:
    pessoa: str | None = None  # uid ou e-mail
    alvo_id: str | None = None
    acao: Acao | None = None
    # Qualquer uma delas (a tela "Quem acessou" pede as três de acesso de uma vez).
    acoes: tuple[Acao, ...] | None = None
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
        if getattr(registro, campo) != valor:
            return False
    if filtro.alvo_id is not None and registro.alvo_id != filtro.alvo_id:
        return False
    if filtro.acao is not None and registro.acao != filtro.acao:
        return False
    if filtro.acoes is not None and registro.acao not in filtro.acoes:
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
    return PaginaDeAuditoria(*um_alem_do_limite(registros, limite))


def criar_rotas_da_auditoria(repositorio: RepositorioDeAuditoria) -> APIRouter:
    rotas = APIRouter(prefix="/admin/auditoria")

    @rotas.get("")
    def listar(
        _pessoa: Annotated[
            Usuario,
            Depends(
                exige("auditoria.ver", "Chave de sistema não consulta a auditoria")
            ),
        ],
        pessoa: Annotated[str | None, LinhaDaConsulta(254)] = None,
        alvo: Annotated[str | None, LinhaDaConsulta(200)] = None,
        acao: Annotated[list[Acao] | None, Query()] = None,
        de: AwareDatetime | None = None,
        ate: AwareDatetime | None = None,
        limite: Annotated[int, Query(ge=1, le=LIMITE_MAXIMO)] = LIMITE_PADRAO,
        cursor: Annotated[str | None, LinhaDaConsulta(500)] = None,
    ) -> JSONResponse:
        if de is not None and ate is not None and de > ate:
            raise HTTPException(422, "Período invertido: `de` depois de `ate`")
        filtro = FiltroDeAuditoria(
            pessoa=pessoa,
            alvo_id=alvo,
            acao=acao[0] if acao and len(acao) == 1 else None,
            acoes=tuple(acao) if acao and len(acao) > 1 else None,
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
