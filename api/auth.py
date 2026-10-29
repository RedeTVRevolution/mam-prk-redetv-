from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict


class Usuario(BaseModel):
    model_config = ConfigDict(frozen=True)

    uid: str
    email: str


class TokenInvalido(Exception):
    """O token não foi emitido pelo Identity Platform, expirou ou está adulterado."""


class VerificadorDeToken(Protocol):
    """Porta para o Identity Platform; os testes usam uma versão falsa."""

    def verificar(self, token: str) -> Usuario: ...


def usuario_autenticado(request: Request) -> Usuario:
    esquema, _, token = request.headers.get("Authorization", "").partition(" ")
    if esquema.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    verificador: VerificadorDeToken = request.app.state.verificador
    try:
        return verificador.verificar(token)
    except TokenInvalido:
        raise HTTPException(
            status_code=401, headers={"WWW-Authenticate": "Bearer"}
        ) from None


UsuarioAutenticado = Annotated[Usuario, Depends(usuario_autenticado)]
