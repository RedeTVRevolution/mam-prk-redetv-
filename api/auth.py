from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Protocol

import jwt
from fastapi import Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

PREFIXO_PROTEGIDO = "/v1"
# Única rota de /v1 sem token: a checagem de saúde do Cloud Run e do deploy.
CAMINHO_HEALTH = "/v1/health"


class Usuario(BaseModel):
    model_config = ConfigDict(frozen=True)

    uid: str
    email: str


class Sistema(BaseModel):
    """Sistema da RedeTV que chama `/v1` com chave de API."""

    model_config = ConfigDict(frozen=True)

    sistema: str


Chamador = Usuario | Sistema


class ChaveInvalida(Exception):
    """A chave de API é desconhecida, foi adulterada ou tem o segredo errado."""


class TokenInvalido(Exception):
    """O token não foi emitido pelo Identity Platform, expirou ou está adulterado."""


class VerificadorDeToken(Protocol):
    """Porta para o Identity Platform; os testes usam uma versão falsa."""

    def verificar(self, token: str) -> Usuario: ...


class VerificadorDeChave(Protocol):
    """Porta para as chaves de API (`api.chaves`); os testes usam uma versão falsa."""

    def verificar(self, chave: str) -> Sistema: ...


# Chaves públicas que assinam os tokens do Identity Platform.
URL_DAS_CHAVES = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"


class VerificadorIdentityPlatform:
    """Confere o token de sessão do Identity Platform. O MFA é obrigatório aqui,
    e não só no Identity Platform: um token sem o segundo fator TOTP é recusado."""

    def __init__(
        self, projeto: str, chave_publica: Callable[[str], Any] | None = None
    ) -> None:
        self._projeto = projeto
        if chave_publica is None:
            # O PyJWKClient guarda as chaves e só busca de novo se aparecer uma desconhecida.
            cliente = jwt.PyJWKClient(URL_DAS_CHAVES)
            chave_publica = lambda token: cliente.get_signing_key_from_jwt(token).key
        self._chave_publica = chave_publica

    def verificar(self, token: str) -> Usuario:
        try:
            claims = jwt.decode(
                token,
                self._chave_publica(token),
                algorithms=["RS256"],
                audience=self._projeto,
                issuer=f"https://securetoken.google.com/{self._projeto}",
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWKClientConnectionError:
            raise  # Google fora do ar não é token inválido: vira 500, não 401.
        except jwt.PyJWTError:
            raise TokenInvalido from None
        if (
            not claims["sub"]
            or claims.get("firebase", {}).get("sign_in_second_factor") != "totp"
        ):
            raise TokenInvalido
        return Usuario(uid=claims["sub"], email=claims.get("email", ""))


async def _autenticar(request: Request) -> Chamador | None:
    autorizacao = request.headers.get("Authorization", "")
    chave = request.headers.get("X-API-Key", "")
    if autorizacao and chave:
        return None  # Os dois juntos: ambíguo.
    # Numa thread: buscar as chaves do Google e o Firestore são E/S síncrona.
    if chave:
        chaves: VerificadorDeChave = request.app.state.chaves
        try:
            return await run_in_threadpool(chaves.verificar, chave)
        except ChaveInvalida:
            return None
    esquema, _, token = autorizacao.partition(" ")
    token = token.strip()
    if esquema.lower() != "bearer" or not token:
        return None
    verificador: VerificadorDeToken = request.app.state.verificador
    try:
        return await run_in_threadpool(verificador.verificar, token)
    except TokenInvalido:
        return None


def _protegido(caminho: str) -> bool:
    if caminho == CAMINHO_HEALTH:
        return False
    return caminho == PREFIXO_PROTEGIDO or caminho.startswith(PREFIXO_PROTEGIDO + "/")


async def exigir_autenticacao(
    request: Request, seguinte: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Middleware: todo `/v1`, com qualquer método e caminho, menos
    `/v1/health`, passa pela autenticação (Bearer de pessoa ou `X-API-Key` de sistema, nunca os dois) antes do roteamento, para que 404, 405 ou redirecionamento não respondam
    a quem não se autenticou."""
    if not _protegido(request.url.path):
        return await seguinte(request)
    chamador = await _autenticar(request)
    if chamador is None:
        return JSONResponse(
            {"detail": "Not authenticated"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.chamador = chamador
    return await seguinte(request)


def chamador_autenticado(request: Request) -> Chamador:
    chamador: Chamador = request.state.chamador
    return chamador


ChamadorAutenticado = Annotated[Chamador, Depends(chamador_autenticado)]
