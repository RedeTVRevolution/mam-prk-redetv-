"""Imagens da web como entrada hostil (#111): imagens sintéticas."""

import io
from typing import Any, Self

import pytest
import requests
from PIL import Image

from api.imagens_hostis import (
    HOST_DO_THUMBNAIL,
    ImagemRecusada,
    baixar_original,
    baixar_thumbnail,
    recodificar,
)

THUMB = f"https://{HOST_DO_THUMBNAIL}/images?q=tbn:AAA"
PUBLICO = ["93.184.216.34"]


def imagem(
    formato: str = "PNG", tamanho: tuple[int, int] = (64, 48), **kw: Any
) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", tamanho, (200, 30, 30)).save(saida, format=formato, **kw)
    return saida.getvalue()


def jpeg_com_metadados() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Camera Secreta"  # Make
    exif[0x8825] = {1: "S", 2: (23.0, 33.0, 0.0)}  # GPS
    return imagem("JPEG", exif=exif, icc_profile=b"perfil-falso" * 10)


class Resposta:
    def __init__(
        self, corpo: bytes, status: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        self.corpo = corpo
        self.status_code = status
        self.headers = headers or {}

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def iter_content(self, chunk_size: int) -> Any:
        for i in range(0, len(self.corpo), chunk_size):
            yield self.corpo[i : i + chunk_size]


class Sessao:
    def __init__(self, *respostas: Resposta | Exception) -> None:
        self.respostas = list(respostas)
        self.urls: list[str] = []
        self.opcoes: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> Resposta:
        self.urls.append(url)
        self.opcoes.append(kwargs)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def resolve(*enderecos: str) -> Any:
    return lambda host: list(enderecos)


# --- recodificação ---------------------------------------------------------


def test_o_jpeg_regravado_nao_tem_metadados() -> None:
    antes = Image.open(io.BytesIO(jpeg_com_metadados()))
    assert antes.info.get("exif") and antes.info.get("icc_profile")

    depois = Image.open(
        io.BytesIO(recodificar(jpeg_com_metadados(), max_bytes=10**6, max_pixels=10**6))
    )

    assert depois.format == "JPEG"
    assert "exif" not in depois.info and "icc_profile" not in depois.info
    assert len(depois.getexif()) == 0
    assert depois.size == (64, 48)


def test_png_e_webp_viram_jpeg() -> None:
    for formato in ("PNG", "WEBP"):
        saida = recodificar(imagem(formato), max_bytes=10**6, max_pixels=10**6)

        assert Image.open(io.BytesIO(saida)).format == "JPEG"


def test_png_com_transparencia_vira_jpeg_sobre_fundo_branco() -> None:
    entrada = io.BytesIO()
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(entrada, format="PNG")

    saida = Image.open(
        io.BytesIO(recodificar(entrada.getvalue(), max_bytes=10**6, max_pixels=10**6))
    )

    assert saida.convert("RGB").getpixel((4, 4)) == (255, 255, 255)


@pytest.mark.parametrize(
    "dados",
    [
        b"<html>nao sou imagem</html>",
        b"GIF89a" + bytes(50),
        imagem("GIF"),
        imagem("BMP"),
        imagem("PNG")[:40],
        b"",
    ],
)
def test_tipo_falso_ou_corrompido_e_recusado(dados: bytes) -> None:
    with pytest.raises(ImagemRecusada):
        recodificar(dados, max_bytes=10**6, max_pixels=10**6)


def test_acima_do_limite_de_bytes_e_recusado() -> None:
    dados = imagem()

    with pytest.raises(ImagemRecusada, match="bytes"):
        recodificar(dados, max_bytes=len(dados) - 1, max_pixels=10**6)


def test_acima_do_limite_de_pixels_e_recusado() -> None:
    with pytest.raises(ImagemRecusada, match="pixels"):
        recodificar(imagem(tamanho=(100, 100)), max_bytes=10**6, max_pixels=9999)


# --- thumbnail -------------------------------------------------------------


def test_thumbnail_do_host_fixado_vira_jpeg_limpo() -> None:
    sessao = Sessao(Resposta(jpeg_com_metadados()))

    saida = baixar_thumbnail(THUMB, sessao)

    assert Image.open(io.BytesIO(saida)).format == "JPEG"
    assert sessao.urls == [THUMB]
    assert sessao.opcoes[0]["allow_redirects"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://exemplo.com/foto.jpg",
        f"https://{HOST_DO_THUMBNAIL}.exemplo.com/x",
        f"https://exemplo.com/{HOST_DO_THUMBNAIL}",
        f"https://{HOST_DO_THUMBNAIL}@exemplo.com/x",
        f"http://{HOST_DO_THUMBNAIL}/x",
        f"https://{HOST_DO_THUMBNAIL}:8443/x",
        "https://encrypted-tbn1.gstatic.com/x",
        "file:///etc/passwd",
    ],
)
def test_thumbnail_de_host_fora_da_lista_e_recusado_sem_baixar(url: str) -> None:
    sessao = Sessao()

    with pytest.raises(ImagemRecusada):
        baixar_thumbnail(url, sessao)

    assert sessao.urls == []


def test_thumbnail_nao_segue_redirecionamento() -> None:
    sessao = Sessao(Resposta(b"", 302, {"Location": "http://10.0.0.1/x"}))

    with pytest.raises(ImagemRecusada):
        baixar_thumbnail(THUMB, sessao)

    assert len(sessao.urls) == 1


def test_thumbnail_com_tipo_falso_e_tamanho_alem_do_limite_sao_recusados() -> None:
    with pytest.raises(ImagemRecusada):
        baixar_thumbnail(THUMB, Sessao(Resposta(b"MZ\x90\x00" + bytes(100))))
    with pytest.raises(ImagemRecusada, match="bytes"):
        baixar_thumbnail(THUMB, Sessao(Resposta(bytes(1_000_001))))


def test_falha_de_rede_do_thumbnail_e_recusa() -> None:
    with pytest.raises(ImagemRecusada):
        baixar_thumbnail(THUMB, Sessao(requests.ConnectionError("x")))


# --- original --------------------------------------------------------------


def test_original_por_https_vira_jpeg_limpo() -> None:
    sessao = Sessao(Resposta(jpeg_com_metadados()))

    saida = baixar_original(
        "https://exemplo.com/f.jpg", sessao, resolver=resolve(*PUBLICO)
    )

    assert "exif" not in Image.open(io.BytesIO(saida)).info


@pytest.mark.parametrize(
    "url",
    [
        "http://exemplo.com/f.jpg",
        "ftp://exemplo.com/f.jpg",
        "https://u:s@exemplo.com/f",
    ],
)
def test_original_fora_do_https_e_recusado(url: str) -> None:
    sessao = Sessao()

    with pytest.raises(ImagemRecusada):
        baixar_original(url, sessao, resolver=resolve(*PUBLICO))

    assert sessao.urls == []


@pytest.mark.parametrize(
    "endereco",
    [
        "10.0.0.5",
        "127.0.0.1",
        "169.254.169.254",
        "192.168.1.1",
        "::1",
        "fd00::1",
        "::ffff:10.0.0.1",
    ],
)
def test_original_que_resolve_para_endereco_privado_e_recusado(endereco: str) -> None:
    sessao = Sessao()

    with pytest.raises(ImagemRecusada, match="privado"):
        baixar_original("https://exemplo.com/f.jpg", sessao, resolver=resolve(endereco))

    assert sessao.urls == []


def test_original_so_segue_redirecionamento_para_endereco_publico() -> None:
    destinos = {"exemplo.com": PUBLICO, "cdn.exemplo.com": PUBLICO}
    sessao = Sessao(
        Resposta(b"", 301, {"Location": "https://cdn.exemplo.com/f.jpg"}),
        Resposta(imagem()),
    )

    baixar_original("https://exemplo.com/f.jpg", sessao, resolver=lambda h: destinos[h])

    assert sessao.urls == ["https://exemplo.com/f.jpg", "https://cdn.exemplo.com/f.jpg"]


@pytest.mark.parametrize(
    "destino", ["https://interno/f.jpg", "http://cdn.exemplo.com/f"]
)
def test_redirecionamento_para_endereco_privado_ou_http_e_recusado(
    destino: str,
) -> None:
    destinos = {
        "exemplo.com": PUBLICO,
        "interno": ["10.1.2.3"],
        "cdn.exemplo.com": PUBLICO,
    }
    sessao = Sessao(Resposta(b"", 302, {"Location": destino}))

    with pytest.raises(ImagemRecusada):
        baixar_original(
            "https://exemplo.com/f.jpg", sessao, resolver=lambda h: destinos[h]
        )

    assert len(sessao.urls) == 1


def test_original_com_redirecionamentos_demais_e_recusado() -> None:
    laco = Resposta(b"", 302, {"Location": "https://exemplo.com/f.jpg"})
    sessao = Sessao(*[laco] * 10)

    with pytest.raises(ImagemRecusada, match="redirecionamentos"):
        baixar_original("https://exemplo.com/f.jpg", sessao, resolver=resolve(*PUBLICO))


def test_original_acima_do_limite_de_bytes_e_recusado_enquanto_baixa() -> None:
    sessao = Sessao(Resposta(bytes(5_000_001)))

    with pytest.raises(ImagemRecusada, match="bytes"):
        baixar_original("https://exemplo.com/f.jpg", sessao, resolver=resolve(*PUBLICO))


def test_original_que_demora_alem_do_prazo_e_recusado() -> None:
    relogio = iter([0.0, 5.0, 100.0, 200.0, 300.0])
    sessao = Sessao(Resposta(bytes(200_000)))

    with pytest.raises(ImagemRecusada, match="prazo"):
        baixar_original(
            "https://exemplo.com/f.jpg",
            sessao,
            resolver=resolve(*PUBLICO),
            relogio=lambda: next(relogio),
        )
    assert sessao.opcoes[0]["timeout"] > 0
