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


def _cliente() -> TestClient:
    verificador: VerificadorDeToken = VerificadorFalso(
        {"token-bom": Usuario(uid="u1", email="ana@redetv.com.br")}
    )
    return TestClient(criar_app(verificador))


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
    assert resposta.json() == {"uid": "u1", "email": "ana@redetv.com.br"}


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


def test_caminho_que_so_comeca_com_v1_nao_e_protegido() -> None:
    assert _cliente().get("/v1x").status_code == 404
