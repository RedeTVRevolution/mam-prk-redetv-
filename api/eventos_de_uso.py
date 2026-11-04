"""Eventos de uso (E9, #279): quem fez o quê e quando, para o painel da diretoria.

Cada ação relevante (login, envio, fim de processamento, busca, correção e chamada de
API) vira um evento no Pub/Sub; uma assinatura do BigQuery o grava na tabela de eventos
(`infra/modulos/mam/eventos_de_uso.tf`). O evento só leva o id de quem agiu (nunca nome
nem e-mail) e, na busca, o tamanho da consulta e os filtros, nunca o texto. Falha ao
publicar não derruba a ação: vai ao log. O Pub/Sub fica atrás da porta `Eventos`.
"""

import base64
import json
import logging
import uuid
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from api.auth import Chamador, Sistema

log = logging.getLogger(__name__)

TipoDeEvento = Literal[
    "login", "envio", "fim_de_processamento", "busca", "correcao", "chamada_de_api"
]
Quem = tuple[Literal["usuario", "sistema"], str]

# (método, caminho a partir de /v1, corpo) -> (status HTTP, resposta em JSON)
Transporte = Callable[[str, str, dict[str, Any] | None], tuple[int, dict[str, Any]]]


class Filtro(BaseModel):
    model_config = ConfigDict(frozen=True)

    nome: str
    valor: str


class EventoDeUso(BaseModel):
    """O que vai no tópico. Os campos são os do `evento_de_uso.proto`: o esquema do
    tópico e a tabela do BigQuery saem dele, e um teste confere que são os mesmos."""

    model_config = ConfigDict(frozen=True)

    id: str
    tipo: TipoDeEvento
    quando: datetime
    quem_tipo: Literal["usuario", "sistema"]
    quem_id: str
    job_id: str | None = None
    programa: str | None = None
    # `envio`: tamanho do arquivo.
    tamanho_bytes: int | None = None
    # `fim_de_processamento`: `concluido` ou `falhou`, o código da falha e quanto o Job
    # levou, do registro ao fim.
    estado: str | None = None
    codigo_falha: str | None = None
    segundos_de_processamento: int | None = None
    # `busca`: só o tamanho da consulta (em caracteres, ou em bytes na busca por
    # imagem; nenhum na de parecidos, que parte de um plano) e os filtros; o texto
    # nunca sai da API.
    tamanho_da_consulta: int | None = None
    # `busca`: quantos vídeos a busca trouxe (0 é busca sem resultado).
    n_resultados: int | None = None
    filtros: list[Filtro] = []
    # `correcao`: o tipo do registro de Correção (`fala.texto`, `pessoa.renomear`...,
    # ou `desfazer`, `descartar`, `aprovar`, `recusar`).
    tipo_de_correcao: str | None = None
    # `chamada_de_api`: método, rota (com `{job_id}`, sem os valores) e status.
    metodo: str | None = None
    rota: str | None = None
    status: int | None = None

    def para_json(self) -> dict[str, Any]:
        """O corpo da mensagem: sem os vazios, e `quando` em microssegundos desde 1970
        (o que a assinatura do BigQuery grava como TIMESTAMP)."""
        corpo = self.model_dump(mode="json", exclude_none=True, exclude={"quando"})
        if not self.filtros:
            corpo.pop("filtros", None)
        corpo["quando"] = round(self.quando.timestamp() * 1_000_000)
        return corpo


class Eventos(Protocol):
    def publicar(self, evento: EventoDeUso) -> None: ...


class EventosEmMemoria:
    """O dublê dos testes."""

    def __init__(self) -> None:
        self.publicados: list[EventoDeUso] = []

    def publicar(self, evento: EventoDeUso) -> None:
        self.publicados.append(evento)


class SemEventos:
    """Onde não há tópico (máquina local, testes): descarta."""

    def publicar(self, evento: EventoDeUso) -> None:
        return None


class EventosEmSegundoPlano:
    """Publica numa thread à parte: a resposta a quem usa não espera o Pub/Sub. A
    falha, que já não tem a quem voltar, vai ao log."""

    def __init__(self, eventos: Eventos, executor: Executor | None = None) -> None:
        self._eventos = eventos
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="eventos-de-uso"
        )

    def publicar(self, evento: EventoDeUso) -> None:
        self._executor.submit(self._publicar, evento)

    def _publicar(self, evento: EventoDeUso) -> None:
        try:
            self._eventos.publicar(evento)
        except Exception:
            log.exception("não consegui publicar o evento de uso %s", evento.tipo)


class ErroAoPublicarUso(Exception):
    pass


class EventosPubSub:
    def __init__(self, topico: str, transporte: Transporte) -> None:
        # `projects/<p>/topics/<t>`
        self._topico = topico
        self._transporte = transporte

    def publicar(self, evento: EventoDeUso) -> None:
        """Uma tentativa só: o evento de uso não vale uma espera na ação do usuário."""
        dados = base64.b64encode(json.dumps(evento.para_json()).encode()).decode()
        corpo = {
            "messages": [
                {
                    "data": dados,
                    "attributes": {"evento_id": evento.id, "tipo": evento.tipo},
                }
            ]
        }
        status, resposta = self._transporte("POST", f"{self._topico}:publish", corpo)
        if status != 200:
            detalhe = resposta.get("error", {}).get("status", "")
            raise ErroAoPublicarUso(f"Pub/Sub respondeu {status} {detalhe}".strip())


def quem_do_chamador(chamador: Chamador) -> Quem:
    if isinstance(chamador, Sistema):
        return "sistema", chamador.sistema
    return "usuario", chamador.uid


def registrar(
    eventos: Eventos,
    tipo: TipoDeEvento,
    quem: Quem,
    quando: datetime,
    *,
    id: str | None = None,
    **dados: Any,
) -> None:
    """Monta e publica o evento. Qualquer falha vai ao log e não ao chamador: a ação já
    aconteceu e não há o que desfazer."""
    try:
        eventos.publicar(
            EventoDeUso(
                id=id or uuid.uuid4().hex,
                tipo=tipo,
                quando=quando.astimezone(UTC),
                quem_tipo=quem[0],
                quem_id=quem[1],
                **dados,
            )
        )
    except Exception:
        log.exception("não consegui publicar o evento de uso %s", tipo)
