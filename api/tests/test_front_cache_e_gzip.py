"""Cabeçalhos de cache do front e gzip das respostas grandes (#558)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from api.jobs import aceita_gzip
from api.main import _GZipQueRespeitaQZero, criar_app

GRANDE = "console.log('aaaaaaaaaaaaaaaa');" * 200  # bem acima de 1 KB
IMUTAVEL = "public, max-age=31536000, immutable"


@pytest.fixture
def cliente(tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("<div id=root></div>" + "x" * 2000)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-abc123.js").write_text(GRANDE)
    (tmp_path / "assets" / "pequeno.js").write_text("1")
    (tmp_path / "assets" / "foto.png").write_bytes(b"\x89PNG" + b"0" * 5000)
    (tmp_path / "sw.js").write_text("self.addEventListener('fetch', () => {})")
    return TestClient(criar_app(pasta_web=tmp_path))


def test_assets_versionados_tem_cache_longo_e_imutavel(cliente: TestClient) -> None:
    resposta = cliente.get("/assets/app-abc123.js")

    assert resposta.headers["cache-control"] == IMUTAVEL
    assert resposta.headers["etag"]


@pytest.mark.parametrize("caminho", ["/", "/index.html", "/video/abc", "/sw.js"])
def test_o_resto_do_front_revalida_pelo_etag(cliente: TestClient, caminho: str) -> None:
    resposta = cliente.get(caminho)

    assert resposta.status_code == 200
    assert resposta.headers["cache-control"] == "no-cache"


def test_asset_ausente_sem_extensao_nao_ganha_cache_longo(cliente: TestClient) -> None:
    resposta = cliente.get("/assets/sumiu")

    assert resposta.headers["cache-control"] == "no-cache"


def test_gzip_nas_respostas_grandes(cliente: TestClient) -> None:
    resposta = cliente.get("/assets/app-abc123.js", headers={"Accept-Encoding": "gzip"})

    assert resposta.headers["content-encoding"] == "gzip"
    assert resposta.text == GRANDE  # o cliente já descomprimiu


def test_sem_gzip_abaixo_de_1_kb() -> None:
    # Direto no middleware; pela app inteira, o teste é o do `/v1/health` abaixo.
    async def pequena(request: Request) -> Response:
        return Response("a" * 1000)

    app = _GZipQueRespeitaQZero(
        Starlette(routes=[Route("/", pequena)]), minimum_size=1024, compresslevel=6
    )

    resposta = TestClient(app).get("/", headers={"Accept-Encoding": "gzip"})

    assert "content-encoding" not in resposta.headers


@pytest.mark.parametrize(
    "cabecalho",
    ["*;q=1, gzip;q=0", "gzip;q=0, *;q=1", "gzip;q=0, *", "*, gzip;q=0"],
)
def test_gzip_explicito_prevalece_sobre_o_curinga_em_qualquer_ordem(
    cabecalho: str,
) -> None:
    assert aceita_gzip(cabecalho) is False


@pytest.mark.parametrize("cabecalho", ["*;q=0, gzip", "gzip, *;q=0", "*", "gzip;q=0.5"])
def test_aceita_gzip_quando_nao_recusado(cabecalho: str) -> None:
    assert aceita_gzip(cabecalho) is True


def test_sem_gzip_com_curinga_e_gzip_q_zero_pela_app(cliente: TestClient) -> None:
    resposta = cliente.get(
        "/assets/app-abc123.js", headers={"Accept-Encoding": "*;q=1, gzip;q=0"}
    )

    assert "content-encoding" not in resposta.headers


def test_resposta_pequena_da_app_inteira_sai_sem_gzip(cliente: TestClient) -> None:
    resposta = cliente.get("/v1/health", headers={"Accept-Encoding": "gzip"})

    assert resposta.json() == {"status": "ok"}
    assert "content-encoding" not in resposta.headers
    assert resposta.headers[
        "x-content-type-options"
    ]  # a pilha de segurança segue de fora


def test_sem_gzip_com_q_zero(cliente: TestClient) -> None:
    resposta = cliente.get(
        "/assets/app-abc123.js", headers={"Accept-Encoding": "gzip;q=0, identity"}
    )

    assert "content-encoding" not in resposta.headers
    assert resposta.text == GRANDE


def test_sem_gzip_em_imagem(cliente: TestClient) -> None:
    resposta = cliente.get("/assets/foto.png", headers={"Accept-Encoding": "gzip"})

    assert "content-encoding" not in resposta.headers


def test_sem_gzip_em_resposta_parcial(cliente: TestClient) -> None:
    resposta = cliente.get(
        "/assets/app-abc123.js",
        headers={"Accept-Encoding": "gzip", "Range": "bytes=0-1999"},
    )

    assert resposta.status_code == 206
    assert "content-encoding" not in resposta.headers
