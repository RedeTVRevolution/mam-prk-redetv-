"""Cabeçalhos de segurança em toda resposta do `mam-web` (#372)."""

from pathlib import Path

import pytest
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


def test_erro_404_da_api_traz_os_cabecalhos(cliente: TestClient) -> None:
    resposta = cliente.get("/v1/nao-existe")

    assert resposta.status_code in {401, 404}
    assert resposta.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in resposta.headers


def test_valores_combinados() -> None:
    assert CABECALHOS_DE_SEGURANCA["X-Content-Type-Options"] == "nosniff"
    assert (
        CABECALHOS_DE_SEGURANCA["Referrer-Policy"] == "strict-origin-when-cross-origin"
    )
    assert CABECALHOS_DE_SEGURANCA["Strict-Transport-Security"] == "max-age=31536000"


def test_csp_tem_o_storage_em_img_media_e_connect_src() -> None:
    diretivas = {
        d.split()[0]: d.split()[1:]
        for d in CABECALHOS_DE_SEGURANCA["Content-Security-Policy"].split("; ")
    }

    for diretiva in ("img-src", "media-src", "connect-src"):
        assert STORAGE in diretivas[diretiva], diretiva
    assert diretivas["frame-ancestors"] == ["'none'"]
