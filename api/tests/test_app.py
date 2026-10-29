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
