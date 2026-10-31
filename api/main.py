import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.auth import (
    CAMINHO_HEALTH,
    PREFIXO_PROTEGIDO,
    ChamadorAutenticado,
    ChaveInvalida,
    Sistema,
    TokenInvalido,
    Usuario,
    VerificadorDeChave,
    VerificadorDeToken,
    VerificadorIdentityPlatform,
    exigir_autenticacao,
)
from api.correcoes import (
    RepositorioDeAprovacao,
    RepositorioDeAprovacaoEmMemoria,
    RepositorioDeCorrecoes,
    RepositorioDeCorrecoesEmMemoria,
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
    papeis_da_pessoa,
)
from api.nuvem import (
    ArmazenamentoStorage,
    RepositorioDeAprovacaoFirestore,
    RepositorioDeCorrecoesFirestore,
    RepositorioDePapeisFirestore,
    RepositorioFirestore,
)
from api.papeis import (
    Papel,
    Permissao,
    RepositorioDePapeis,
    RepositorioDePapeisEmMemoria,
    admins_de,
    permissoes_de,
)
from api.programas import PERFIS

# Build do front (`npm run build`). Sem ele, só a API sobe.
PASTA_WEB = Path(__file__).resolve().parent.parent / "web" / "dist"


class _SemVerificador:
    """Sem projeto do Identity Platform (testes e máquina local): nega tudo."""

    def verificar(self, token: str) -> Usuario:
        raise TokenInvalido


class _SemChaves:
    """Sem adaptador de chaves de API: recusa toda chave."""

    def verificar(self, chave: str) -> Sistema:
        raise ChaveInvalida


class UsuarioComPapeis(Usuario):
    papeis: list[Papel]
    permissoes: list[Permissao]


def criar_app(
    verificador: VerificadorDeToken | None = None,
    repositorio: RepositorioDeJobs | None = None,
    armazenamento: Armazenamento | None = None,
    chaves: VerificadorDeChave | None = None,
    papeis: RepositorioDePapeis | None = None,
    admins_emergencia: str | None = None,
    correcoes: RepositorioDeCorrecoes | None = None,
    aprovacao: RepositorioDeAprovacao | None = None,
    tamanho_maximo_bytes: int = TAMANHO_MAXIMO_PADRAO_BYTES,
    relogio: Callable[[], datetime] = agora_utc,
    pasta_web: Path = PASTA_WEB,
) -> FastAPI:
    app = FastAPI(title="MAM RedeTV")

    @app.exception_handler(ServicoIndisponivel)
    def _indisponivel(_request: Request, _erro: ServicoIndisponivel) -> JSONResponse:
        return JSONResponse({"detail": "Serviço indisponível"}, status_code=503)

    @app.exception_handler(TipoNaoSuportado)
    def _tipo_errado(_request: Request, _erro: TipoNaoSuportado) -> JSONResponse:
        return JSONResponse({"detail": "Só video/mp4"}, status_code=415)

    app.state.verificador = verificador or _SemVerificador()
    app.state.chaves = chaves or _SemChaves()
    app.state.papeis = papeis or RepositorioDePapeisEmMemoria()
    app.state.admins = admins_de(admins_emergencia)
    app.middleware("http")(exigir_autenticacao)

    @app.get(CAMINHO_HEALTH)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    v1 = APIRouter(prefix=PREFIXO_PROTEGIDO)

    @v1.get("/eu")
    def eu(
        request: Request, chamador: ChamadorAutenticado
    ) -> UsuarioComPapeis | Sistema:
        if isinstance(chamador, Sistema):
            return chamador
        efetivos = papeis_da_pessoa(request, chamador)
        return UsuarioComPapeis(
            **chamador.model_dump(),
            papeis=efetivos,
            permissoes=sorted(permissoes_de(efetivos)),
        )

    @v1.get("/programas")
    def programas(_chamador: ChamadorAutenticado) -> list[str]:
        """Os programas com perfil, para o envio escolher."""
        return sorted(PERFIS)

    v1.include_router(
        criar_rotas(
            repositorio or RepositorioIndisponivel(),
            armazenamento or ArmazenamentoIndisponivel(),
            tamanho_maximo_bytes,
            relogio,
            correcoes or RepositorioDeCorrecoesEmMemoria(),
            aprovacao or RepositorioDeAprovacaoEmMemoria(),
        )
    )
    app.include_router(v1)
    if pasta_web.is_dir():
        app.mount("/", StaticFiles(directory=pasta_web, html=True))
    return app


# No Cloud Run, o Terraform define o projeto; fora dele, a API nega todo token.
_projeto = os.environ.get("GCP_PROJECT_ID")
if _projeto:
    app = criar_app(
        VerificadorIdentityPlatform(_projeto),
        RepositorioFirestore(firestore.Client(project=_projeto)),
        ArmazenamentoStorage(
            ClienteStorage(project=_projeto),
            os.environ["BUCKET_QUARENTENA"],
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        papeis=RepositorioDePapeisFirestore(firestore.Client(project=_projeto)),
        admins_emergencia=os.environ.get("ADMINS_EMERGENCIA"),
        correcoes=RepositorioDeCorrecoesFirestore(firestore.Client(project=_projeto)),
        aprovacao=RepositorioDeAprovacaoFirestore(firestore.Client(project=_projeto)),
    )
else:
    app = criar_app()
