import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from api.auth import TokenInvalido, Usuario, VerificadorIdentityPlatform

PROJETO = "mam-dev"
_CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OUTRA_CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _verificador() -> VerificadorIdentityPlatform:
    return VerificadorIdentityPlatform(
        PROJETO, chave_publica=lambda _token: _CHAVE.public_key()
    )


def _token(chave: Any = _CHAVE, **mudancas: Any) -> str:
    agora = int(time.time())
    claims: dict[str, Any] = {
        "iss": f"https://securetoken.google.com/{PROJETO}",
        "aud": PROJETO,
        "sub": "u1",
        "email": "ana@redetv.com.br",
        "email_verified": True,
        "iat": agora,
        "exp": agora + 3600,
        "firebase": {"sign_in_provider": "password", "sign_in_second_factor": "totp"},
    }
    claims.update(mudancas)
    return jwt.encode(claims, chave, algorithm="RS256")


def test_token_com_segundo_fator_vira_usuario() -> None:
    assert _verificador().verificar(_token()) == Usuario(
        uid="u1", email="ana@redetv.com.br", email_verificado=True
    )


@pytest.mark.parametrize("claim", [False, None])
def test_email_sem_verificacao_fica_nao_verificado(claim: bool | None) -> None:
    claims = {"email_verified": claim} if claim is not None else {}
    token = _token(**claims)
    if claim is None:
        # Sem o claim: remonta o token sem `email_verified`.
        agora = int(time.time())
        token = jwt.encode(
            {
                "iss": f"https://securetoken.google.com/{PROJETO}",
                "aud": PROJETO,
                "sub": "u1",
                "email": "ana@redetv.com.br",
                "iat": agora,
                "exp": agora + 3600,
                "firebase": {"sign_in_second_factor": "totp"},
            },
            _CHAVE,
            algorithm="RS256",
        )

    assert _verificador().verificar(token).email_verificado is False


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(
            _token(firebase={"sign_in_provider": "password"}), id="sem segundo fator"
        ),
        pytest.param(
            _token(
                firebase={
                    "sign_in_provider": "password",
                    "sign_in_second_factor": "phone",
                }
            ),
            id="segundo fator que não é TOTP",
        ),
        pytest.param(_token(aud="outro-projeto"), id="outro projeto"),
        pytest.param(
            _token(iss="https://securetoken.google.com/outro"), id="outro emissor"
        ),
        pytest.param(_token(exp=int(time.time()) - 60), id="expirado"),
        pytest.param(_token(sub=""), id="sem uid"),
        pytest.param(_token(chave=_OUTRA_CHAVE), id="assinatura de outra chave"),
        pytest.param("nao-e-jwt", id="lixo"),
    ],
)
def test_token_recusado(token: str) -> None:
    with pytest.raises(TokenInvalido):
        _verificador().verificar(token)
