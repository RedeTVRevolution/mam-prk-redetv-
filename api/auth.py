from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol

from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

PREFIXO_PROTEGIDO = "/v1"
# Única rota de /v1 sem token: a checagem de saúde do Cloud Run e do deploy.
CAMINHO_HEALTH = "/v1/health"


class Usuario(BaseModel):
    model_config = ConfigDict(frozen=True)

    uid: str
    email: str


class TokenInvalido(Exception):
    """O token não foi emitido pelo Identity Platform, expirou ou está adulterado."""


class VerificadorDeToken(Protocol):
    """Porta para o Identity Platform; os testes usam uma versão falsa."""

    def verificar(self, token: str) -> Usuario: ...


def _autenticar(request: Request) -> Usuario | None:
    esquema, _, token = request.headers.get("Authorization", "").partition(" ")
    token = token.strip()
    if esquema.lower() != "bearer" or not token:
        return None
    verificador: VerificadorDeToken = request.app.state.verificador
    try:
        return verificador.verificar(token)
    except TokenInvalido:
        return None


def _protegido(caminho: str) -> bool:
    if caminho == CAMINHO_HEALTH:
        return False
    return caminho == PREFIXO_PROTEGIDO or caminho.startswith(PREFIXO_PROTEGIDO + "/")


async def exigir_token(
    request: Request, seguinte: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Middleware: todo `/v1`, com qualquer método e caminho, passa pelo token
    antes do roteamento, para que 404, 405 ou redirecionamento não respondam
    a quem não se autenticou."""
    if not _protegido(request.url.path):
        return await seguinte(request)
    usuario = _autenticar(request)
    if usuario is None:
        return JSONResponse(
            {"detail": "Not authenticated"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.usuario = usuario
    return await seguinte(request)


def usuario_autenticado(request: Request) -> Usuario:
    usuario: Usuario = request.state.usuario
    return usuario


UsuarioAutenticado = Annotated[Usuario, Depends(usuario_autenticado)]
