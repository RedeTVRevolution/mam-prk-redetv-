from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from api.auth import (
    PREFIXO_PROTEGIDO,
    TokenInvalido,
    Usuario,
    UsuarioAutenticado,
    VerificadorDeToken,
    exigir_token,
)
from api.jobs import (
    TAMANHO_MAXIMO_PADRAO_BYTES,
    Armazenamento,
    ArmazenamentoIndisponivel,
    RepositorioDeJobs,
    RepositorioIndisponivel,
    ServicoIndisponivel,
    TipoNaoSuportado,
    agora_utc,
    criar_rotas,
)


class _SemVerificador:
    """Padrão até o verificador real do Identity Platform existir: nega tudo."""

    def verificar(self, token: str) -> Usuario:
        raise TokenInvalido


def criar_app(
    verificador: VerificadorDeToken | None = None,
    repositorio: RepositorioDeJobs | None = None,
    armazenamento: Armazenamento | None = None,
    tamanho_maximo_bytes: int = TAMANHO_MAXIMO_PADRAO_BYTES,
    relogio: Callable[[], datetime] = agora_utc,
) -> FastAPI:
    app = FastAPI(title="MAM RedeTV")

    @app.exception_handler(ServicoIndisponivel)
    def _indisponivel(_request: Request, _erro: ServicoIndisponivel) -> JSONResponse:
        return JSONResponse({"detail": "Serviço indisponível"}, status_code=503)

    @app.exception_handler(TipoNaoSuportado)
    def _tipo_errado(_request: Request, _erro: TipoNaoSuportado) -> JSONResponse:
        return JSONResponse({"detail": "Só video/mp4"}, status_code=415)

    app.state.verificador = verificador or _SemVerificador()
    app.middleware("http")(exigir_token)

    v1 = APIRouter(prefix=PREFIXO_PROTEGIDO)

    @v1.get("/eu")
    def eu(usuario: UsuarioAutenticado) -> Usuario:
        return usuario

    v1.include_router(
        criar_rotas(
            repositorio or RepositorioIndisponivel(),
            armazenamento or ArmazenamentoIndisponivel(),
            tamanho_maximo_bytes,
            relogio,
        )
    )
    app.include_router(v1)
    return app


app = criar_app()
