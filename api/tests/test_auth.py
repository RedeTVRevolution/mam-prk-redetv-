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


def test_rota_inexistente_em_v1_sem_token_tambem_recebe_401() -> None:
    assert _cliente().get("/v1/jobs").status_code == 401
