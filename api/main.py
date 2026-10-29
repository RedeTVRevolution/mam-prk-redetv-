from fastapi import APIRouter, FastAPI

from api.auth import (
    PREFIXO_PROTEGIDO,
    TokenInvalido,
    Usuario,
    UsuarioAutenticado,
    VerificadorDeToken,
    exigir_token,
)


class _SemVerificador:
    """Padrão até o verificador real do Identity Platform existir: nega tudo."""

    def verificar(self, token: str) -> Usuario:
        raise TokenInvalido


def criar_app(verificador: VerificadorDeToken | None = None) -> FastAPI:
    app = FastAPI(title="MAM RedeTV")
    app.state.verificador = verificador or _SemVerificador()
    app.middleware("http")(exigir_token)

    v1 = APIRouter(prefix=PREFIXO_PROTEGIDO)

    @v1.get("/eu")
    def eu(usuario: UsuarioAutenticado) -> Usuario:
        return usuario

    app.include_router(v1)
    return app


app = criar_app()
