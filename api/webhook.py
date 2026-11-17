"""Webhook assinado (E7): avisa um sistema da RedeTV quando um job seu termina.

A URL de callback é entrada hostil: só https, sem credenciais, e nunca um host que
aponte para a rede interna (SSRF). A checagem roda no registro e de novo na entrega,
sobre os IPs resolvidos. A rede, o DNS e o segredo ficam atrás de portas.
"""

import hmac
import http.client
import ipaddress
import json
import secrets
import socket
import ssl
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from api.modelo_do_job import FIM, CodigoDeFalha, Job

# Um evento assinado há mais que isto é tratado pelo cliente como repetido.
TOLERANCIA_DA_DATA = timedelta(minutes=5)


class UrlInvalida(ValueError):
    pass


class HostNaoResolve(UrlInvalida):
    """O DNS não respondeu: no registro recusa, na entrega é falha passageira."""


Resolvedor = Callable[[str], list[str]]


def resolver_dns(host: str) -> list[str]:
    return sorted(
        {str(i[4][0]) for i in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    )


def _ip_interno(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # `is_global` também barra faixas que `is_private` deixa passar, como o CGNAT
    # (100.64.0.0/10); multicast pode ser global, mas não é destino de POST.
    return not ip.is_global or ip.is_multicast


def _resolvidos(
    host: str, resolver: Resolvedor
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        enderecos = [ipaddress.ip_address(ip) for ip in resolver(host)]
    except (OSError, ValueError) as e:
        raise HostNaoResolve("o host da URL do webhook não resolve") from e
    if not enderecos:
        raise HostNaoResolve("o host da URL do webhook não resolve")
    return enderecos


def validar_url(url: str, resolver: Resolvedor = resolver_dns) -> list[str]:
    """Devolve os IPs do host, todos públicos; levanta `UrlInvalida` se a URL não
    serve de callback."""
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
    if any(_ip_interno(ip) for ip in enderecos):
        raise UrlInvalida("a URL do webhook aponta para um endereço interno")
    return [str(ip) for ip in enderecos]


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
    job: Job,
    repositorio: RepositorioDeWebhooks,
    agora: datetime,
    id: str | None = None,
) -> Evento | None:
    """Evento de um job que terminou, se o sistema dono tem webhook. Job de pessoa
    e job cancelado não geram evento."""
    if job.sistema is None or job.estado not in FIM:
        return None
    if repositorio.obter(job.sistema) is None:
        return None
    concluido = job.estado == "concluido"
    return Evento(
        id=id or str(uuid.uuid4()),
        tipo="job.concluido" if concluido else "job.falhou",
        job_id=job.id,
        estado="concluido" if concluido else "falhou",
        codigo_falha=job.codigo_falha,
        data=agora,
    )


class PortaHttp(Protocol):
    def enviar(
        self, url: str, ips: list[str], corpo: bytes, cabecalhos: dict[str, str]
    ) -> int:
        """POST; devolve o status. Falha de rede levanta `OSError`.

        Conecta num dos `ips`, já validados, sem resolver o host de novo (senão o DNS
        pode trocar de resposta entre a checagem e a conexão), com o host da URL no
        SNI e no `Host`. Não segue redirecionamento: um 3xx volta como status."""
        ...


# Tempo total do POST, somando as tentativas em cada IP: cabe no ack de 60 s do Pub/Sub,
# com o cofre e o Firestore.
PRAZO_DO_POST_S = 30.0


class _ConexaoNoIp(http.client.HTTPSConnection):
    """Conecta no `ip`; o host da URL fica no SNI, na checagem do certificado e no `Host`."""

    def __init__(
        self, host: str, porta: int, ip: str, contexto: ssl.SSLContext, prazo_s: float
    ) -> None:
        super().__init__(host, porta, timeout=prazo_s, context=contexto)
        self._ip = ip
        self._contexto = contexto

    def connect(self) -> None:
        bruto = socket.create_connection((self._ip, self.port), self.timeout)
        try:
            self.sock = self._contexto.wrap_socket(bruto, server_hostname=self.host)
        except BaseException:
            bruto.close()
            raise


def _derrubar(sock: socket.socket) -> None:
    # `shutdown`, e não `close`: só ele acorda um `recv` parado em outra thread.
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


class HttpNoIpValidado:
    """A `PortaHttp` real, só com a biblioteca padrão."""

    def __init__(
        self, contexto: ssl.SSLContext | None = None, prazo_s: float = PRAZO_DO_POST_S
    ) -> None:
        self._contexto = contexto or ssl.create_default_context()
        self._prazo_s = prazo_s

    def enviar(
        self, url: str, ips: list[str], corpo: bytes, cabecalhos: dict[str, str]
    ) -> int:
        partes = urlsplit(url)
        caminho = (partes.path or "/") + (f"?{partes.query}" if partes.query else "")
        fim = time.monotonic() + self._prazo_s
        erro: OSError = OSError("nenhum IP para conectar")
        # IPv4 primeiro: o Cloud Run pode não ter saída IPv6.
        for ip in sorted(ips, key=lambda ip: ":" in ip):
            restante = fim - time.monotonic()
            if restante <= 0:
                break
            conexao = _ConexaoNoIp(
                partes.hostname or "", partes.port or 443, ip, self._contexto, restante
            )
            try:
                conexao.connect()
            except OSError as e:
                # Só a conexão que falhou passa ao próximo IP; o POST enviado nunca repete.
                erro = e
                conexao.close()
                continue
            # O timeout do socket vale por operação: um destino que goteja bytes o
            # renova sempre. No fim do prazo, o vigia derruba a conexão.
            vigia = threading.Timer(fim - time.monotonic(), _derrubar, [conexao.sock])
            vigia.start()
            try:
                conexao.request("POST", caminho, body=corpo, headers=cabecalhos)
                return conexao.getresponse().status
            except http.client.HTTPException as e:
                raise OSError(f"resposta inválida do destino: {e!r}") from e
            finally:
                vigia.cancel()
                conexao.close()
        raise erro


def _repetivel(status: int) -> bool:
    return status in (408, 429) or status >= 500


def _tentar(
    evento: Evento,
    registro: RegistroDeWebhook,
    segredo: str,
    corpo: bytes,
    http: PortaHttp,
    resolver: Resolvedor,
    relogio: Callable[[], datetime],
) -> int:
    ips = validar_url(registro.url, resolver)
    data = relogio().isoformat()
    cabecalhos = {
        "Content-Type": "application/json",
        "X-Webhook-Id": evento.id,
        "X-Webhook-Data": data,
        "X-Webhook-Assinatura": assinar(segredo, data, corpo),
    }
    try:
        return http.enviar(registro.url, ips, corpo, cabecalhos)
    except OSError:
        return 503


Resultado = Literal["entregue", "repetir", "descartar"]


def entregar_uma_vez(
    evento: Evento,
    registro: RegistroDeWebhook,
    cofre: Cofre,
    http: PortaHttp,
    *,
    resolver: Resolvedor = resolver_dns,
    relogio: Callable[[], datetime],
) -> Resultado:
    """Uma tentativa só: quem repete é a assinatura push do Pub/Sub, com espera e fila
    de mensagens mortas. `repetir` é status repetível ou DNS fora do ar; `descartar` é
    o que repetir não conserta (4xx, URL que virou inválida, sistema sem segredo). O id
    do evento é o mesmo em toda tentativa, para o cliente descartar o repetido."""
    segredo = cofre.obter(registro.sistema)
    if segredo is None:
        return "descartar"
    corpo = _corpo(evento)
    try:
        status = _tentar(evento, registro, segredo, corpo, http, resolver, relogio)
    except HostNaoResolve:
        return "repetir"
    except UrlInvalida:
        return "descartar"
    if 200 <= status < 300:
        return "entregue"
    return "repetir" if _repetivel(status) else "descartar"


def _corpo(evento: Evento) -> bytes:
    return json.dumps(
        evento.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
    ).encode()


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
