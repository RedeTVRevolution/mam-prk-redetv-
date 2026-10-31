from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app, criar_app


def test_app_publica_o_openapi() -> None:
    resposta = TestClient(app).get("/openapi.json")

    assert resposta.status_code == 200
    assert resposta.json()["info"]["title"] == "MAM RedeTV"


def test_health_responde_200_sem_token() -> None:
    resposta = TestClient(app).get("/v1/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_raiz_serve_a_pagina_do_build_do_react(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<div id=root></div>")

    resposta = TestClient(criar_app(pasta_web=tmp_path)).get("/")

    assert resposta.status_code == 200
    assert resposta.text == "<div id=root></div>"


def _app_com_build(tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return TestClient(criar_app(pasta_web=tmp_path))


def test_endereco_do_front_devolve_o_index_com_200(tmp_path: Path) -> None:
    cliente = _app_com_build(tmp_path)
    for caminho in ("/video/qualquer", "/acervo", "/amostra", "/outra/rota/funda"):
        resposta = cliente.get(caminho)

        assert resposta.status_code == 200, caminho
        assert resposta.text == "<div id=root></div>"


def test_v1_desconhecido_continua_404_em_json(tmp_path: Path) -> None:
    resposta = _app_com_build(tmp_path).get("/v1/inexistente")

    assert resposta.status_code in (401, 404)
    assert resposta.headers["content-type"].startswith("application/json")


def test_arquivo_do_build_e_servido_como_arquivo(tmp_path: Path) -> None:
    resposta = _app_com_build(tmp_path).get("/assets/app.js")

    assert resposta.status_code == 200
    assert resposta.text == "console.log(1)"


def test_arquivo_inexistente_de_assets_continua_404(tmp_path: Path) -> None:
    assert _app_com_build(tmp_path).get("/assets/nao-existe.js").status_code == 404
