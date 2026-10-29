from fastapi.testclient import TestClient

from api.main import app


def test_app_publica_o_openapi() -> None:
    resposta = TestClient(app).get("/openapi.json")

    assert resposta.status_code == 200
    assert resposta.json()["info"]["title"] == "MAM RedeTV"
