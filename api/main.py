from fastapi import APIRouter, Depends, FastAPI, HTTPException

from api.auth import (
    TokenInvalido,
    Usuario,
    UsuarioAutenticado,
    VerificadorDeToken,
    usuario_autenticado,
)


class _SemVerificador:
    """Padrão até o verificador real do Identity Platform existir: nega tudo."""

    def verificar(self, token: str) -> Usuario:
        raise TokenInvalido


def criar_app(verificador: VerificadorDeToken | None = None) -> FastAPI:
    app = FastAPI(title="MAM RedeTV")
    app.state.verificador = verificador or _SemVerificador()

    v1 = APIRouter(prefix="/v1", dependencies=[Depends(usuario_autenticado)])

    @v1.get("/eu")
    def eu(usuario: UsuarioAutenticado) -> dict[str, str]:
        return {"uid": usuario.uid, "email": usuario.email}

    # Sem isto, um caminho desconhecido em /v1 daria 404 antes de checar o token.
    @v1.api_route(
        "/{caminho:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def desconhecida(caminho: str) -> None:
        raise HTTPException(status_code=404)

    app.include_router(v1)
    return app


app = criar_app()
