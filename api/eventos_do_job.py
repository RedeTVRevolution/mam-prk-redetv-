"""Eventos de fim de Job no Pub/Sub (E7, #273).

Quando um Job passa a `concluido` ou `falhou`, o evento do webhook vai a um tópico, e
a entrega sai de uma assinatura push que chama a API (`POST /interno/webhook`), com
espera e fila de mensagens mortas do Pub/Sub, em vez de a orquestração chamar o
webhook direto. O id do evento nasce na publicação e vai no `X-Webhook-Id` de toda
tentativa, então o cliente descarta a repetida. A rede e o Pub/Sub ficam atrás de portas.
"""

import base64
import binascii
import json
import logging
import os
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any, Protocol

import google.auth
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from google.auth.transport.requests import AuthorizedSession
from pydantic import BaseModel, ConfigDict, ValidationError

from api.eventos_de_uso import (
    Eventos,
    EventosPubSub,
    Quem,
    SemEventos,
    registrar,
)
from api.jobs import (
    Estado,
    FiltroDeJobs,
    Job,
    PaginaDeJobs,
    RepositorioDeJobs,
    ServicoIndisponivel,
    agora_utc,
)
from api.webhook import (
    Cofre,
    Evento,
    PortaHttp,
    RepositorioDeWebhooks,
    Resolvedor,
    entregar_uma_vez,
    montar_evento,
    resolver_dns,
)

log = logging.getLogger(__name__)

URL_BASE = "https://pubsub.googleapis.com/v1"
CAMINHO_DO_PUSH = "/interno/webhook"
# Status do publish que passam com uma nova tentativa, e a espera antes de cada uma.
STATUS_REPETIVEIS_DO_PUBSUB = {429, 500, 502, 503, 504}
ESPERAS_DO_PUBSUB = (1.0, 2.0)
# O evento de uso não vale uma espera longa na ação de quem o causou.
TEMPO_DO_EVENTO_DE_USO_S = 5.0
FIM_DE_JOB: tuple[Estado, ...] = ("concluido", "falhou")

# (método, caminho a partir de /v1, corpo) -> (status HTTP, resposta em JSON)
Transporte = Callable[[str, str, dict[str, Any] | None], tuple[int, dict[str, Any]]]


class MensagemDeEvento(BaseModel):
    """O que vai no tópico: o evento e o sistema que o recebe."""

    model_config = ConfigDict(frozen=True)

    sistema: str
    evento: Evento


class PublicadorDeEventos(Protocol):
    def publicar(self, mensagem: MensagemDeEvento) -> None: ...


class PublicadorEmMemoria:
    def __init__(self) -> None:
        self.mensagens: list[MensagemDeEvento] = []

    def publicar(self, mensagem: MensagemDeEvento) -> None:
        self.mensagens.append(mensagem)


class ErroDoPubSub(Exception):
    pass


class PublicadorPubSub:
    def __init__(
        self,
        topico: str,
        transporte: Transporte,
        esperar: Callable[[float], None] = time.sleep,
    ) -> None:
        # `projects/<p>/topics/<t>`
        self._topico = topico
        self._transporte = transporte
        self._esperar = esperar

    def publicar(self, mensagem: MensagemDeEvento) -> None:
        """Repete o erro passageiro do Pub/Sub (429, 5xx) algumas vezes: depois que o
        Job mudou de estado, ninguém mais publica esse evento."""
        dados = base64.b64encode(mensagem.model_dump_json().encode()).decode()
        corpo = {
            "messages": [
                {
                    "data": dados,
                    "attributes": {
                        "evento_id": mensagem.evento.id,
                        "tipo": mensagem.evento.tipo,
                    },
                }
            ]
        }
        for espera in (*ESPERAS_DO_PUBSUB, None):
            status, resposta = self._transporte(
                "POST", f"{self._topico}:publish", corpo
            )
            if status not in STATUS_REPETIVEIS_DO_PUBSUB or espera is None:
                break
            self._esperar(espera)
        if status != 200:
            detalhe = resposta.get("error", {}).get("status", "")
            raise ErroDoPubSub(f"Pub/Sub respondeu {status} {detalhe}".strip())


def transporte_do_pubsub(timeout_s: float = 30) -> Transporte:
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/pubsub"]
    )
    sessao = AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]

    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        resposta = sessao.request(  # type: ignore[no-untyped-call]
            metodo, f"{URL_BASE}/{caminho}", json=corpo, timeout=timeout_s
        )
        try:
            return resposta.status_code, resposta.json()
        except ValueError:
            return resposta.status_code, {}

    return transporte


def publicar_fim(
    job: Job,
    webhooks: RepositorioDeWebhooks,
    publicador: PublicadorDeEventos,
    agora: datetime,
) -> bool:
    """Publica o evento do Job que terminou, se o sistema dono tem webhook. Falha do
    Pub/Sub vai ao log e não ao chamador: o Job já mudou de estado e quem o mudou não
    tem o que desfazer. `True` se publicou."""
    try:
        evento = montar_evento(job, webhooks, agora)
        if evento is None or job.sistema is None:
            return False
        publicador.publicar(MensagemDeEvento(sistema=job.sistema, evento=evento))
    except Exception:
        log.exception("não consegui publicar o evento de fim do Job %s", job.id)
        return False
    return True


class RepositorioQuePublicaOFim:
    """Repositório de Jobs que publica o evento a cada transição para `concluido` ou
    `falhou`. As transições do ciclo de vida passam todas por `transitar`; `trocar`
    (correções de estado à mão) não dispara nada, como diz o GLOSSARY."""

    def __init__(
        self,
        repositorio: RepositorioDeJobs,
        webhooks: RepositorioDeWebhooks,
        publicador: PublicadorDeEventos,
        relogio: Callable[[], datetime] = agora_utc,
    ) -> None:
        self._repositorio = repositorio
        self._webhooks = webhooks
        self._publicador = publicador
        self._relogio = relogio

    def salvar(self, job: Job) -> None:
        self._repositorio.salvar(job)

    def criar(self, job: Job) -> bool:
        return self._repositorio.criar(job)

    def obter(self, job_id: str) -> Job | None:
        return self._repositorio.obter(job_id)

    def obter_fila_gpu(self) -> dict[str, Any]:
        return self._repositorio.obter_fila_gpu()

    def obter_varios(self, job_ids: Iterable[str]) -> list[Job]:
        return self._repositorio.obter_varios(job_ids)

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        job = self._repositorio.transitar(job_id, de, mudancas)
        if job is not None and job.estado != de:
            publicar_fim(job, self._webhooks, self._publicador, self._relogio())
        return job

    def acrescentar_ano_da_copia(self, job_id: str, ano: int) -> None:
        self._repositorio.acrescentar_ano_da_copia(job_id, ano)

    def trocar(
        self, job_id: str, mudar: Callable[[Job], dict[str, Any] | None]
    ) -> Job | None:
        return self._repositorio.trocar(job_id, mudar)

    def remover(self, job_id: str) -> None:
        self._repositorio.remover(job_id)

    def listar(self) -> list[Job]:
        return self._repositorio.listar()

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        return self._repositorio.consultar(filtro)

    def contar_criados(self, criado_por: str, desde: datetime) -> int:
        return self._repositorio.contar_criados(criado_por, desde)


def registrar_o_fim(eventos: Eventos, job: Job, agora: datetime) -> None:
    """O evento de uso `fim_de_processamento` do Job que terminou."""
    quem: Quem = (
        ("sistema", job.sistema)
        if job.sistema is not None
        else ("usuario", job.criado_por)
    )
    registrar(
        eventos,
        "fim_de_processamento",
        quem,
        agora,
        job_id=job.id,
        programa=job.programa,
        estado=job.estado,
        codigo_falha=job.codigo_falha,
        segundos_de_processamento=max(
            0, round((agora - job.criado_em).total_seconds())
        ),
        duracao_do_video_ms=(
            round(job.duracao_s * 1000) if job.duracao_s is not None else None
        ),
    )


class RepositorioQueRegistraOFim:
    """Repositório de Jobs que publica o evento de uso (#279) a cada transição para
    `concluido` ou `falhou`. Como no webhook, `trocar` (correção de estado à mão) não
    dispara nada."""

    def __init__(
        self,
        repositorio: RepositorioDeJobs,
        eventos: Eventos,
        relogio: Callable[[], datetime] = agora_utc,
    ) -> None:
        self._repositorio = repositorio
        self._eventos = eventos
        self._relogio = relogio

    def salvar(self, job: Job) -> None:
        self._repositorio.salvar(job)

    def criar(self, job: Job) -> bool:
        return self._repositorio.criar(job)

    def obter(self, job_id: str) -> Job | None:
        return self._repositorio.obter(job_id)

    def obter_fila_gpu(self) -> dict[str, Any]:
        return self._repositorio.obter_fila_gpu()

    def obter_varios(self, job_ids: Iterable[str]) -> list[Job]:
        return self._repositorio.obter_varios(job_ids)

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        job = self._repositorio.transitar(job_id, de, mudancas)
        if job is not None and job.estado != de and job.estado in FIM_DE_JOB:
            registrar_o_fim(self._eventos, job, self._relogio())
        return job

    def acrescentar_ano_da_copia(self, job_id: str, ano: int) -> None:
        self._repositorio.acrescentar_ano_da_copia(job_id, ano)

    def trocar(
        self, job_id: str, mudar: Callable[[Job], dict[str, Any] | None]
    ) -> Job | None:
        return self._repositorio.trocar(job_id, mudar)

    def remover(self, job_id: str) -> None:
        self._repositorio.remover(job_id)

    def listar(self) -> list[Job]:
        return self._repositorio.listar()

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        return self._repositorio.consultar(filtro)

    def contar_criados(self, criado_por: str, desde: datetime) -> int:
        return self._repositorio.contar_criados(criado_por, desde)


def eventos_do_ambiente(
    ambiente: Mapping[str, str],
    transporte: Callable[[float], Transporte] = transporte_do_pubsub,
) -> Eventos:
    """Com `PUBSUB_TOPICO_USO` (o Terraform a define na web e nos Jobs que terminam um
    Job), publica no tópico dos eventos de uso; sem ela, descarta."""
    topico = ambiente.get("PUBSUB_TOPICO_USO")
    if not topico:
        return SemEventos()
    return EventosPubSub(topico, transporte(TEMPO_DO_EVENTO_DE_USO_S))


def repositorio_do_ambiente(
    repositorio: RepositorioDeJobs,
    webhooks: Callable[[], RepositorioDeWebhooks],
    ambiente: Mapping[str, str],
    transporte: Callable[[], Transporte] = transporte_do_pubsub,
    transporte_de_uso: Callable[[float], Transporte] = transporte_do_pubsub,
) -> RepositorioDeJobs:
    """Com `PUBSUB_TOPICO_EVENTOS` (o Terraform a define nos serviços e Jobs que
    terminam um Job), o repositório publica o fim para o webhook; com
    `PUBSUB_TOPICO_USO`, publica também o evento de uso. Sem elas, fica como está."""
    topico = ambiente.get("PUBSUB_TOPICO_EVENTOS")
    if topico:
        repositorio = RepositorioQuePublicaOFim(
            repositorio, webhooks(), PublicadorPubSub(topico, transporte())
        )
    if ambiente.get("PUBSUB_TOPICO_USO"):
        repositorio = RepositorioQueRegistraOFim(
            repositorio,
            eventos_do_ambiente(ambiente, transporte_de_uso),
        )
    return repositorio


def jobs_do_ambiente(cliente: Any) -> RepositorioDeJobs:
    """O repositório do Firestore dos Jobs de processamento onde um Job pode terminar
    (validação, transcrição, OCR e análise). A API não o usa: ela só leva a `cancelado`."""
    from api.nuvem import RepositorioDeWebhooksFirestore, RepositorioFirestore

    return repositorio_do_ambiente(
        RepositorioFirestore(cliente),
        lambda: RepositorioDeWebhooksFirestore(cliente),
        os.environ,
    )


class VerificadorDoPush(Protocol):
    def confere(self, autorizacao: str | None) -> bool:
        """O cabeçalho `Authorization` da chamada é o token da assinatura push."""
        ...


class VerificadorDoPushDoGoogle:
    """Confere o token OIDC que o Pub/Sub assina: audiência da URL e a conta de serviço
    da assinatura (`PUSH_AUDIENCIA`, `PUSH_CONTA`)."""

    def __init__(self, audiencia: str, conta: str) -> None:
        from google.auth.transport import requests as transporte

        self._audiencia = audiencia
        self._conta = conta
        # Uma sessão só, para reaproveitar a conexão com quem serve os certificados.
        self._pedido = transporte.Request()

    def confere(self, autorizacao: str | None) -> bool:
        """Sem os certificados do Google, levanta `ServicoIndisponivel` (503, e o
        Pub/Sub tenta de novo), em vez de recusar um token que pode ser bom."""
        from google.auth.exceptions import TransportError
        from google.oauth2 import id_token

        if not autorizacao or not autorizacao.startswith("Bearer "):
            return False
        try:
            token = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
                autorizacao.removeprefix("Bearer "),
                self._pedido,
                self._audiencia,
            )
        except TransportError as erro:
            raise ServicoIndisponivel("certificados do Google fora do ar") from erro
        except ValueError:
            return False
        return bool(token.get("email_verified")) and token.get("email") == self._conta


def _mensagem(corpo: Any) -> MensagemDeEvento | None:
    try:
        dados = base64.b64decode(corpo["message"]["data"], validate=True)
        return MensagemDeEvento.model_validate_json(dados)
    except (KeyError, TypeError, binascii.Error, ValidationError):
        return None


def criar_rotas_do_push(
    verificador: VerificadorDoPush,
    webhooks: RepositorioDeWebhooks,
    cofre: Cofre,
    http: PortaHttp,
    resolver: Resolvedor = resolver_dns,
    relogio: Callable[[], datetime] = agora_utc,
) -> APIRouter:
    rotas = APIRouter()

    def tratar(autorizacao: str | None, corpo: bytes) -> Response:
        try:
            if not verificador.confere(autorizacao):
                raise HTTPException(401, "Not authenticated")
        except ServicoIndisponivel as erro:
            raise HTTPException(503, str(erro)) from erro
        try:
            mensagem = _mensagem(json.loads(corpo))
        except ValueError:
            mensagem = None
        if mensagem is None:
            # Mensagem que nunca vai ser entendida: confirmar, senão volta até a fila de mortas.
            log.error("mensagem do push fora do formato")
            return Response(status_code=204)
        registro = webhooks.obter(mensagem.sistema)
        if registro is None:
            log.warning("sistema %s sem webhook: evento descartado", mensagem.sistema)
            return Response(status_code=204)
        resultado = entregar_uma_vez(
            mensagem.evento, registro, cofre, http, resolver=resolver, relogio=relogio
        )
        if resultado == "repetir":
            # Fora de 2xx o Pub/Sub tenta de novo, com espera, e depois manda para a fila de mortas.
            raise HTTPException(503, "destino indisponível")
        if resultado == "descartar":
            log.error("evento %s não tem como ser entregue", mensagem.evento.id)
        return Response(status_code=204)

    @rotas.post(CAMINHO_DO_PUSH, status_code=204)
    async def receber(request: Request) -> Response:
        # A conferência do token, o Firestore e a entrega (até 30 s) bloqueiam: rodam
        # fora do laço de eventos, para o destino lento não parar as outras rotas.
        corpo = await request.body()
        return await run_in_threadpool(
            tratar, request.headers.get("authorization"), corpo
        )

    return rotas
