"""Cabeçalhos de segurança em toda resposta do `mam-web` (#372)."""

from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from api.main import CABECALHOS_DE_SEGURANCA, criar_app

STORAGE = "https://storage.googleapis.com"


@pytest.fixture
def cliente(tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "sw.js").write_text("self.addEventListener('fetch', () => {})")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return TestClient(criar_app(pasta_web=tmp_path))


@pytest.mark.parametrize(
    "caminho",
    ["/", "/assets/app.js", "/sw.js", "/health", "/v1/eu", "/assets/nao-existe.js"],
)
def test_toda_resposta_traz_os_quatro_cabecalhos(
    cliente: TestClient, caminho: str
) -> None:
    resposta = cliente.get(caminho)

    for nome, valor in CABECALHOS_DE_SEGURANCA.items():
        assert resposta.headers[nome] == valor, (caminho, nome)
    assert set(CABECALHOS_DE_SEGURANCA) == {
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Strict-Transport-Security",
    }


def test_erro_404_traz_os_cabecalhos(cliente: TestClient) -> None:
    resposta = cliente.get("/assets/nao-existe.js")

    assert resposta.status_code == 404
    for nome, valor in CABECALHOS_DE_SEGURANCA.items():
        assert resposta.headers[nome] == valor, nome


def test_erro_500_nao_tratado_traz_os_cabecalhos(tmp_path: Path) -> None:
    rotas = APIRouter()

    @rotas.get("/interno/quebra")
    def _quebra() -> None:
        raise RuntimeError("quebrou")

    app = criar_app(pasta_web=tmp_path, rotas_do_push=rotas)
    resposta = TestClient(app, raise_server_exceptions=False).get("/interno/quebra")

    assert resposta.status_code == 500
    for nome, valor in CABECALHOS_DE_SEGURANCA.items():
        assert resposta.headers[nome] == valor, nome


def test_valores_combinados() -> None:
    assert CABECALHOS_DE_SEGURANCA["X-Content-Type-Options"] == "nosniff"
    assert (
        CABECALHOS_DE_SEGURANCA["Referrer-Policy"] == "strict-origin-when-cross-origin"
    )
    assert CABECALHOS_DE_SEGURANCA["Strict-Transport-Security"] == "max-age=31536000"


def test_csp_permite_style_inline_so_em_elementos(cliente: TestClient) -> None:
    resposta = cliente.get("/")
    diretivas = {
        d.split()[0]: d.split()[1:]
        for d in resposta.headers["Content-Security-Policy"].split("; ")
    }

    assert diretivas["style-src-elem"] == ["'self'", "'unsafe-inline'"]
    assert diretivas["default-src"] == ["'self'"]
    assert "style-src" not in diretivas
    assert "style-src-attr" not in diretivas


def test_csp_tem_o_storage_em_img_media_e_connect_src() -> None:
    diretivas = {
        d.split()[0]: d.split()[1:]
        for d in CABECALHOS_DE_SEGURANCA["Content-Security-Policy"].split("; ")
    }

    for diretiva in ("img-src", "media-src", "connect-src"):
        assert STORAGE in diretivas[diretiva], diretiva
    assert diretivas["frame-ancestors"] == ["'none'"]
