"""Webhook assinado (E7): avisa um sistema da RedeTV quando um job seu termina.

A URL de callback é entrada hostil: só https, sem credenciais, e nunca um host que
aponte para a rede interna (SSRF). A checagem roda no registro e de novo na entrega,
sobre os IPs resolvidos. A rede, o DNS e o segredo ficam atrás de portas.
"""

import hmac
import ipaddress
import json
import random
import secrets
import socket
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from api.espera import espera_com_jitter
from api.jobs import CodigoDeFalha, Job

REENTREGAS = 8  # novas tentativas depois da primeira
ESPERA_BASE_S = 5.0
ESPERA_TETO_S = 3600.0
# Um evento assinado há mais que isto é tratado pelo cliente como repetido.
TOLERANCIA_DA_DATA = timedelta(minutes=5)
TIMEOUT_DA_ENTREGA_S = 10


class UrlInvalida(ValueError):
    pass


Resolvedor = Callable[[str], list[str]]


def resolver_dns(host: str) -> list[str]:
    return sorted(
        {str(i[4][0]) for i in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    )


def _ip_interno(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolvidos(
    host: str, resolver: Resolvedor
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(ip) for ip in resolver(host)]
    except (OSError, ValueError):
        return []


def validar_url(url: str, resolver: Resolvedor = resolver_dns) -> None:
    """Levanta `UrlInvalida` se a URL não serve de callback."""
    try:
        partes = urlsplit(url)
        host = (partes.hostname or "").rstrip(".").lower()
        partes.port  # noqa: B018 — porta inválida levanta ValueError
    except ValueError as e:
        raise UrlInvalida("URL malformada") from e
    if partes.scheme != "https":
        raise UrlInvalida("a URL do webhook deve ser https")
    if partes.username is not None or partes.password is not None:
        raise UrlInvalida("a URL do webhook não pode ter credenciais")
    if not host:
        raise UrlInvalida("a URL do webhook não tem host")
    if host == "localhost" or host.endswith(".localhost"):
        raise UrlInvalida("a URL do webhook não pode apontar para localhost")
    try:
        enderecos = [ipaddress.ip_address(host)]
    except ValueError:
        enderecos = _resolvidos(host, resolver)
    if not enderecos:
        raise UrlInvalida("o host da URL do webhook não resolve")
    if any(_ip_interno(ip) for ip in enderecos):
        raise UrlInvalida("a URL do webhook aponta para um endereço interno")


class Cofre(Protocol):
    """Porta para o segredo do webhook (no plano, Secret Manager com CMEK)."""

    def guardar(self, sistema: str, segredo: str) -> None: ...

    def obter(self, sistema: str) -> str | None: ...


class CofreEmMemoria:
    def __init__(self) -> None:
        self._segredos: dict[str, str] = {}

    def guardar(self, sistema: str, segredo: str) -> None:
        self._segredos[sistema] = segredo

    def obter(self, sistema: str) -> str | None:
        return self._segredos.get(sistema)


class RegistroDeWebhook(BaseModel):
    """O que fica no repositório: a URL, nunca o segredo."""

    model_config = ConfigDict(frozen=True)

    sistema: str
    url: str


class RepositorioDeWebhooks(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def salvar(self, registro: RegistroDeWebhook) -> None: ...

    def obter(self, sistema: str) -> RegistroDeWebhook | None: ...


class RepositorioDeWebhooksEmMemoria:
    def __init__(self) -> None:
        self._registros: dict[str, RegistroDeWebhook] = {}

    def salvar(self, registro: RegistroDeWebhook) -> None:
        self._registros[registro.sistema] = registro

    def obter(self, sistema: str) -> RegistroDeWebhook | None:
        return self._registros.get(sistema)


def registrar_webhook(
    sistema: str,
    url: str,
    cofre: Cofre,
    repositorio: RepositorioDeWebhooks,
    resolver: Resolvedor = resolver_dns,
) -> str:
    """Valida a URL, guarda o segredo no cofre e devolve o segredo, que só sai daqui.
    Registrar de novo troca a URL e o segredo."""
    validar_url(url, resolver)
    segredo = secrets.token_urlsafe(32)
    cofre.guardar(sistema, segredo)
    repositorio.salvar(RegistroDeWebhook(sistema=sistema, url=url))
    return segredo


def assinar(segredo: str, data: str, corpo: bytes) -> str:
    """HMAC-SHA256 (hexadecimal) sobre `<data>.<corpo>`."""
    return hmac.digest(segredo.encode(), data.encode() + b"." + corpo, sha256).hex()


def verificar_assinatura(
    segredo: str,
    data: str,
    corpo: bytes,
    assinatura: str,
    agora: datetime,
    tolerancia: timedelta = TOLERANCIA_DA_DATA,
) -> bool:
    """O que o cliente faz: confere a assinatura e recusa data fora da tolerância."""
    try:
        enviada = datetime.fromisoformat(data)
    except ValueError:
        return False
    if enviada.tzinfo is None or abs(agora - enviada) > tolerancia:
        return False
    return hmac.compare_digest(assinar(segredo, data, corpo), assinatura)


class Evento(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    tipo: Literal["job.concluido", "job.falhou"]
    job_id: str
    estado: Literal["concluido", "falhou"]
    codigo_falha: CodigoDeFalha | None
    data: datetime


def montar_evento(
    job: Job, repositorio: RepositorioDeWebhooks, agora: datetime
) -> Evento | None:
    """Evento de um job que terminou, se o sistema dono tem webhook. Job de pessoa
    e job cancelado não geram evento."""
    if job.sistema is None or job.estado not in ("concluido", "falhou"):
        return None
    if repositorio.obter(job.sistema) is None:
        return None
    return Evento(
        id=str(uuid.uuid4()),
        tipo="job.concluido" if job.estado == "concluido" else "job.falhou",
        job_id=job.id,
        estado=job.estado,
        codigo_falha=job.codigo_falha,
        data=agora,
    )


class PortaHttp(Protocol):
    def enviar(self, url: str, corpo: bytes, cabecalhos: dict[str, str]) -> int:
        """POST; devolve o status. Falha de rede levanta `OSError`."""
        ...


def _repetivel(status: int) -> bool:
    return status in (408, 429) or status >= 500


def entregar(
    evento: Evento,
    registro: RegistroDeWebhook,
    cofre: Cofre,
    http: PortaHttp,
    *,
    resolver: Resolvedor = resolver_dns,
    dormir: Callable[[float], None] = time.sleep,
    sortear: Callable[[float], float] = lambda teto: random.uniform(0, teto),
    relogio: Callable[[], datetime],
) -> bool:
    """Entrega o evento; `True` se algum POST teve 2xx. Reentregas levam o mesmo id
    de evento e uma data e assinatura novas. A URL é conferida de novo, sobre o IP
    resolvido, antes de cada tentativa."""
    segredo = cofre.obter(registro.sistema)
    if segredo is None:
        return False
    corpo = json.dumps(
        evento.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
    ).encode()
    falhas = 0
    while True:
        try:
            validar_url(registro.url, resolver)
        except UrlInvalida:
            return False
        data = relogio().isoformat()
        cabecalhos = {
            "Content-Type": "application/json",
            "X-Webhook-Id": evento.id,
            "X-Webhook-Data": data,
            "X-Webhook-Assinatura": assinar(segredo, data, corpo),
        }
        try:
            status = http.enviar(registro.url, corpo, cabecalhos)
        except OSError:
            status = 503
        if 200 <= status < 300:
            return True
        if not _repetivel(status) or falhas >= REENTREGAS:
            return False
        dormir(espera_com_jitter(falhas, ESPERA_BASE_S, ESPERA_TETO_S, sortear))
        falhas += 1


def registrar_webhook_main(
    argv: list[str],
    cofre: Cofre,
    repositorio: RepositorioDeWebhooks,
    imprimir: Callable[[str], None] = print,
    resolver: Resolvedor = resolver_dns,
) -> int:
    if len(argv) != 2 or not argv[0] or not argv[1]:
        imprimir("uso: registrar-webhook <nome do sistema> <url https de callback>")
        return 2
    try:
        segredo = registrar_webhook(argv[0], argv[1], cofre, repositorio, resolver)
    except UrlInvalida as erro:
        imprimir(f"URL recusada: {erro}")
        return 2
    imprimir(f"Webhook de {argv[0]} registrado em {argv[1]}")
    imprimir("Guarde o segredo agora: ele não será mostrado de novo.")
    imprimir(segredo)
    return 0
