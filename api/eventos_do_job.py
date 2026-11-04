"""Eventos de fim de Job no Pub/Sub (E7, #273).

Quando um Job passa a `concluido` ou `falhou`, o evento do webhook vai a um tópico, e
a entrega sai de uma assinatura push que chama a API (`POST /interno/webhook`), com
espera e fila de mensagens mortas do Pub/Sub, em vez de a orquestração chamar o
webhook direto. O id do evento nasce na publicação e vai no `X-Webhook-Id` de toda
tentativa, então o cliente descarta a repetida. A rede e o Pub/Sub ficam atrás de portas.
"""

import base64
import binascii
import logging
import os
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

import google.auth
from fastapi import APIRouter, HTTPException, Request, Response
from google.auth.transport.requests import AuthorizedSession
from pydantic import BaseModel, ConfigDict, ValidationError

from api.jobs import Estado, Job, RepositorioDeJobs, agora_utc
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
    def __init__(self, topico: str, transporte: Transporte) -> None:
        # `projects/<p>/topics/<t>`
        self._topico = topico
        self._transporte = transporte

    def publicar(self, mensagem: MensagemDeEvento) -> None:
        dados = base64.b64encode(mensagem.model_dump_json().encode()).decode()
        status, resposta = self._transporte(
            "POST",
            f"{self._topico}:publish",
            {
                "messages": [
                    {
                        "data": dados,
                        "attributes": {
                            "evento_id": mensagem.evento.id,
                            "tipo": mensagem.evento.tipo,
                        },
                    }
                ]
            },
        )
        if status != 200:
            detalhe = resposta.get("error", {}).get("status", "")
            raise ErroDoPubSub(f"Pub/Sub respondeu {status} {detalhe}".strip())


def transporte_do_pubsub() -> Transporte:
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/pubsub"]
    )
    sessao = AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]

    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        resposta = sessao.request(  # type: ignore[no-untyped-call]
            metodo, f"{URL_BASE}/{caminho}", json=corpo, timeout=30
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

    def obter(self, job_id: str) -> Job | None:
        return self._repositorio.obter(job_id)

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        job = self._repositorio.transitar(job_id, de, mudancas)
        if job is not None and job.estado != de:
            publicar_fim(job, self._webhooks, self._publicador, self._relogio())
        return job

    def trocar(
        self, job_id: str, mudar: Callable[[Job], dict[str, Any] | None]
    ) -> Job | None:
        return self._repositorio.trocar(job_id, mudar)

    def remover(self, job_id: str) -> None:
        self._repositorio.remover(job_id)

    def listar(self) -> list[Job]:
        return self._repositorio.listar()

    def consultar(self, filtro: Any) -> Any:
        return self._repositorio.consultar(filtro)


def repositorio_do_ambiente(
    repositorio: RepositorioDeJobs,
    webhooks: Callable[[], RepositorioDeWebhooks],
    ambiente: Mapping[str, str],
    transporte: Callable[[], Transporte] = transporte_do_pubsub,
) -> RepositorioDeJobs:
    """Com `PUBSUB_TOPICO_EVENTOS` (o Terraform a define nos serviços e Jobs que
    terminam um Job), o repositório publica o fim; sem ela, fica como está."""
    topico = ambiente.get("PUBSUB_TOPICO_EVENTOS")
    if not topico:
        return repositorio
    return RepositorioQuePublicaOFim(
        repositorio, webhooks(), PublicadorPubSub(topico, transporte())
    )


def jobs_do_ambiente(cliente: Any) -> RepositorioDeJobs:
    """O repositório do Firestore que os Jobs e a API usam onde um Job pode terminar."""
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
        self._audiencia = audiencia
        self._conta = conta

    def confere(self, autorizacao: str | None) -> bool:
        from google.auth.transport import requests as transporte
        from google.oauth2 import id_token

        if not autorizacao or not autorizacao.startswith("Bearer "):
            return False
        try:
            token = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
                autorizacao.removeprefix("Bearer "),
                transporte.Request(),
                self._audiencia,
            )
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

    @rotas.post(CAMINHO_DO_PUSH, status_code=204)
    async def receber(request: Request) -> Response:
        if not verificador.confere(request.headers.get("authorization")):
            raise HTTPException(401, "Not authenticated")
        try:
            mensagem = _mensagem(await request.json())
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

    return rotas
