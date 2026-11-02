"""Imagens da web são entrada hostil (#111, ADR 0005).

Primeiro o `thumbnail` do Google, com o host fixado; o `original` só quando o
thumbnail não serve, por https, com limite de tamanho e de tempo e sem seguir
redirecionamento para endereço privado. Em qualquer caso o tipo vem do conteúdo (não do
cabeçalho nem da extensão), há limite de bytes e de pixels, e a imagem é decodificada e
regravada em JPEG sem metadados: o que sai daqui nunca é o arquivo que veio da rede.
"""

import io
import ipaddress
import socket
import time
from collections.abc import Callable, Iterator
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image, UnidentifiedImageError

HOST_DO_THUMBNAIL = "encrypted-tbn0.gstatic.com"
FORMATOS_ACEITOS = {"JPEG", "PNG", "WEBP"}
LIMITE_DE_BYTES_DO_THUMBNAIL = 1_000_000
LIMITE_DE_PIXELS_DO_THUMBNAIL = 2_000_000
LIMITE_DE_BYTES_DO_ORIGINAL = 5_000_000
LIMITE_DE_PIXELS_DO_ORIGINAL = 25_000_000
PRAZO_DO_ORIGINAL_S = 10.0
PRAZO_DO_THUMBNAIL_S = 10.0
REDIRECIONAMENTOS_DO_ORIGINAL = 3
QUALIDADE_DO_JPEG = 90
# Cada leitura é no máximo um `recv` (com o `timeout` do pedido): o prazo total é
# conferido entre elas, e um servidor que pinga um byte por vez não o contorna.
TAMANHO_DA_LEITURA = 16384


class ImagemRecusada(Exception):
    """A imagem não passou: host, tipo, tamanho, pixels, tempo ou endereço."""


class AcimaDoLimiteDeBytes(ImagemRecusada):
    def __init__(self) -> None:
        super().__init__("acima do limite de bytes")


class AcimaDoLimiteDePixels(ImagemRecusada):
    def __init__(self) -> None:
        super().__init__("acima do limite de pixels")


class SessaoDeDownload(Protocol):
    """O que o download usa de `requests.Session`."""

    def get(self, url: str, **kwargs: Any) -> Any: ...


Resolvedor = Callable[[str], list[str]]


def resolver_dns(host: str) -> list[str]:
    try:
        return [
            str(i[4][0]) for i in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ]
    except OSError as e:
        raise ImagemRecusada("host não resolve") from e


def recodificar(
    dados: bytes,
    *,
    max_bytes: int,
    max_pixels: int,
    formatos: frozenset[str] | set[str] = FORMATOS_ACEITOS,
) -> bytes:
    """Confere o conteúdo e devolve um JPEG novo, sem metadados."""
    if len(dados) > max_bytes:
        raise AcimaDoLimiteDeBytes
    try:
        with Image.open(io.BytesIO(dados)) as imagem:
            # O JPEG de celular com o bloco MPF abre como MPO; vale o primeiro quadro.
            formato = "JPEG" if imagem.format == "MPO" else imagem.format
            if formato not in formatos:
                raise ImagemRecusada("tipo de imagem não aceito")
            largura, altura = imagem.size
            if largura * altura > max_pixels:
                raise AcimaDoLimiteDePixels
            imagem.load()
            colorida = imagem.convert("RGBA")
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        ValueError,
    ) as e:
        raise ImagemRecusada("não é uma imagem válida") from e
    # Imagem nova: o EXIF, o ICC e o resto de `info` ficam no arquivo de origem.
    limpa = Image.new("RGB", colorida.size, (255, 255, 255))
    limpa.paste(colorida, mask=colorida.getchannel("A"))
    saida = io.BytesIO()
    limpa.save(saida, format="JPEG", quality=QUALIDADE_DO_JPEG)
    return saida.getvalue()


def _corpo(
    resposta: Any, max_bytes: int, prazo: float, relogio: Callable[[], float]
) -> bytes:
    pedacos: list[bytes] = []
    total = 0
    for pedaco in _pedacos(resposta):
        total += len(pedaco)
        if total > max_bytes:
            raise AcimaDoLimiteDeBytes
        if relogio() > prazo:
            raise ImagemRecusada("demorou além do prazo")
        pedacos.append(pedaco)
    return b"".join(pedacos)


def _pedacos(resposta: Any) -> Iterator[bytes]:
    # `iter_content` espera juntar o pedaço inteiro antes de devolver; `read1` devolve o
    # que chegou numa leitura só.
    while pedaco := resposta.raw.read1(TAMANHO_DA_LEITURA, decode_content=True):
        yield pedaco


def _https(url: str) -> Any:
    partes = urlsplit(url)
    if (
        partes.scheme != "https"
        or not partes.hostname
        or partes.port not in (None, 443)
    ):
        raise ImagemRecusada("só https na porta padrão")
    if partes.username or partes.password:
        raise ImagemRecusada("endereço com credencial")
    return partes


def baixar_thumbnail(
    url: str,
    sessao: SessaoDeDownload,
    *,
    relogio: Callable[[], float] = time.monotonic,
) -> bytes:
    """O thumbnail, só do host fixado, sem redirecionamento."""
    partes = _https(url)
    if partes.hostname != HOST_DO_THUMBNAIL:
        raise ImagemRecusada("host fora da lista")
    prazo = relogio() + PRAZO_DO_THUMBNAIL_S
    dados = _baixar(sessao, url, LIMITE_DE_BYTES_DO_THUMBNAIL, prazo, relogio)
    return recodificar(
        dados,
        max_bytes=LIMITE_DE_BYTES_DO_THUMBNAIL,
        max_pixels=LIMITE_DE_PIXELS_DO_THUMBNAIL,
    )


def _baixar(
    sessao: SessaoDeDownload,
    url: str,
    max_bytes: int,
    prazo: float,
    relogio: Callable[[], float],
) -> bytes:
    try:
        resposta = sessao.get(
            url,
            stream=True,
            allow_redirects=False,
            timeout=PRAZO_DO_THUMBNAIL_S,
            headers={"Accept": "image/*"},
        )
        with resposta:
            if resposta.status_code != 200:
                raise ImagemRecusada(f"HTTP {resposta.status_code}")
            return _corpo(resposta, max_bytes, prazo, relogio)
    except requests.RequestException as e:
        raise ImagemRecusada("falha de rede") from e


def _publico(host: str, resolver: Resolvedor) -> None:
    enderecos = resolver(host)
    if not enderecos:
        raise ImagemRecusada("host não resolve")
    for endereco in enderecos:
        try:
            ip = ipaddress.ip_address(endereco.split("%")[0])
        except ValueError as e:
            raise ImagemRecusada("endereço inválido") from e
        if not ip.is_global or getattr(ip, "ipv4_mapped", None) is not None:
            raise ImagemRecusada("endereço privado")


def baixar_original(
    url: str,
    sessao: SessaoDeDownload,
    *,
    resolver: Resolvedor = resolver_dns,
    relogio: Callable[[], float] = time.monotonic,
) -> bytes:
    """O original, por https, seguindo no máximo alguns redirecionamentos e só enquanto
    o endereço de cada passo for público."""
    prazo = relogio() + PRAZO_DO_ORIGINAL_S
    atual = url
    for _ in range(REDIRECIONAMENTOS_DO_ORIGINAL + 1):
        partes = _https(atual)
        assert partes.hostname is not None
        _publico(partes.hostname, resolver)
        try:
            resposta = sessao.get(
                atual,
                stream=True,
                allow_redirects=False,
                timeout=PRAZO_DO_ORIGINAL_S,
                headers={"Accept": "image/*"},
            )
            with resposta:
                if resposta.status_code in (301, 302, 303, 307, 308):
                    destino = resposta.headers.get("Location")
                    if not destino:
                        raise ImagemRecusada("redirecionamento sem destino")
                    atual = urljoin(atual, destino)
                    continue
                if resposta.status_code != 200:
                    raise ImagemRecusada(f"HTTP {resposta.status_code}")
                dados = _corpo(resposta, LIMITE_DE_BYTES_DO_ORIGINAL, prazo, relogio)
        except requests.RequestException as e:
            raise ImagemRecusada("falha de rede") from e
        return recodificar(
            dados,
            max_bytes=LIMITE_DE_BYTES_DO_ORIGINAL,
            max_pixels=LIMITE_DE_PIXELS_DO_ORIGINAL,
        )
    raise ImagemRecusada("redirecionamentos demais")
