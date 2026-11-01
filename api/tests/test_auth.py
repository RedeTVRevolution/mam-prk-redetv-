from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.auth import TokenInvalido, Usuario, VerificadorDeToken
from api.main import criar_app


class VerificadorFalso:
    """Identity Platform simulado: só aceita tokens combinados de antemão."""

    def __init__(self, tokens: dict[str, Usuario]) -> None:
        self._tokens = tokens

    def verificar(self, token: str) -> Usuario:
        try:
            return self._tokens[token]
        except KeyError:
            raise TokenInvalido from None


def _cliente(pasta_web: Path | None = None) -> TestClient:
    verificador: VerificadorDeToken = VerificadorFalso(
        {"token-bom": Usuario(uid="u1", email="ana@redetv.com.br")}
    )
    if pasta_web is None:
        return TestClient(criar_app(verificador))
    return TestClient(criar_app(verificador, pasta_web=pasta_web))


def test_v1_sem_token_recebe_401() -> None:
    assert _cliente().get("/v1/eu").status_code == 401


def test_v1_com_token_invalido_recebe_401() -> None:
    resposta = _cliente().get("/v1/eu", headers={"Authorization": "Bearer ruim"})

    assert resposta.status_code == 401


def test_v1_com_esquema_de_autorizacao_errado_recebe_401() -> None:
    resposta = _cliente().get("/v1/eu", headers={"Authorization": "Basic token-bom"})

    assert resposta.status_code == 401


def test_v1_com_token_valido_devolve_o_usuario() -> None:
    resposta = _cliente().get("/v1/eu", headers={"Authorization": "Bearer token-bom"})

    assert resposta.status_code == 200
    assert resposta.json()["uid"] == "u1"
    assert resposta.json()["email"] == "ana@redetv.com.br"


@pytest.mark.parametrize("metodo", ["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS"])
@pytest.mark.parametrize("caminho", ["/v1", "/v1/", "/v1/eu", "/v1/jobs"])
def test_qualquer_metodo_e_caminho_em_v1_sem_token_recebe_401(
    metodo: str, caminho: str
) -> None:
    resposta = _cliente().request(metodo, caminho, follow_redirects=False)

    assert resposta.status_code == 401


def test_rota_inexistente_em_v1_com_token_valido_recebe_404() -> None:
    resposta = _cliente().get("/v1/nada", headers={"Authorization": "Bearer token-bom"})

    assert resposta.status_code == 404


def test_caminho_que_so_comeca_com_v1_nao_e_protegido(tmp_path: Path) -> None:
    # Fora de `/v1`, é endereço do front: devolve o index.html, sem pedir token.
    (tmp_path / "index.html").write_text("<div id=root></div>")

    resposta = _cliente(tmp_path).get("/v1x")

    assert resposta.status_code == 200
    assert resposta.text == "<div id=root></div>"


def test_rota_inexistente_em_v1_com_build_montado_continua_404_em_json(
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text("<div id=root></div>")

    resposta = _cliente(tmp_path).get(
        "/v1/inexistente", headers={"Authorization": "Bearer token-bom"}
    )

    assert resposta.status_code == 404
    assert resposta.headers["content-type"].startswith("application/json")
