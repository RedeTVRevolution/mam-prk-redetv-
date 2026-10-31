import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from starlette.exceptions import HTTPException as ExcecaoHttp
from starlette.responses import Response
from starlette.types import Scope

from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
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
from api.busca import Busca, Ranking, RankingEmOrdem
from api.catalogo import Catalogo, CatalogoEmMemoria
from api.catalogo_de_correcoes import CatalogoDeCorrecoes
from api.catalogo_de_correcoes import catalogo as catalogo_de_correcoes
from api.correcoes import (
    RepositorioDeAprovacao,
    RepositorioDeAprovacaoEmMemoria,
    RepositorioDeCorrecoes,
    RepositorioDeCorrecoesEmMemoria,
)
from api.entendimento_da_consulta import ModelArmor
from api.gemini import Chamada, ErroHttp, Transporte
from api.indexacao import reindexar
from api.indice_da_busca import IndiceDaBusca, IndiceEmMemoria
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
    CatalogoFirestore,
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
from api.rota_da_busca import (
    CONSULTAS_POR_MINUTO,
    TEMPO_MAXIMO_S,
    criar_rotas_da_busca,
)

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


class _SemModelo:
    """Sem modelo ligado à busca: toda consulta cai no plano B."""

    def gerar(self, chamada: Chamada) -> str:
        raise ErroHttp(503)


class _SemModelArmor:
    """Sem Model Armor, não há veredito: o modelo nunca é chamado (plano B)."""

    def acusa_injecao(self, texto: str) -> bool:
        raise RuntimeError("Model Armor não ligado")


class _FrontComEnderecos(StaticFiles):
    """O front tem endereço por tela (`/video/{id}`): fora de `/v1`, o que não é arquivo
    do build devolve o `index.html`, e o roteador do front decide a tela."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except ExcecaoHttp as erro:
            ultimo = path.rsplit("/", 1)[-1]
            if erro.status_code != 404 or "." in ultimo:
                raise
            if path == "v1" or path.startswith("v1/"):
                raise
            return await super().get_response("index.html", scope)


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
    catalogo: Catalogo | None = None,
    indice: IndiceDaBusca | None = None,
    transporte_da_consulta: Transporte | None = None,
    armor: ModelArmor | None = None,
    ranking: Ranking | None = None,
    busca_por_minuto: int = CONSULTAS_POR_MINUTO,
    tempo_maximo_da_busca_s: float = TEMPO_MAXIMO_S,
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

    @v1.get("/correcoes/catalogo")
    def tipos_de_correcao(_chamador: ChamadorAutenticado) -> CatalogoDeCorrecoes:
        """Os tipos de Correção e os vocabulários que o front mostra."""
        return catalogo_de_correcoes()

    repositorio_de_jobs = repositorio or RepositorioIndisponivel()
    armazenamento_dos_jobs = armazenamento or ArmazenamentoIndisponivel()
    repositorio_de_correcoes = correcoes or RepositorioDeCorrecoesEmMemoria()
    indice_da_busca = indice or IndiceEmMemoria()
    catalogo_de_pessoas = catalogo or CatalogoEmMemoria()
    v1.include_router(
        criar_rotas(
            repositorio_de_jobs,
            armazenamento_dos_jobs,
            tamanho_maximo_bytes,
            relogio,
            repositorio_de_correcoes,
            aprovacao or RepositorioDeAprovacaoEmMemoria(),
            catalogo_de_pessoas,
            lambda job: reindexar(
                job,
                repositorio_de_jobs,
                armazenamento_dos_jobs,
                repositorio_de_correcoes,
                indice_da_busca,
                relogio,
            ),
        )
    )
    v1.include_router(
        criar_rotas_da_busca(
            Busca(
                transporte=transporte_da_consulta or _SemModelo(),
                catalogo=catalogo_de_pessoas,
                armor=armor or _SemModelArmor(),
                programas=sorted(PERFIS),
                indice=indice_da_busca,
                ranking=ranking or RankingEmOrdem(),
                repositorio=repositorio_de_jobs,
                armazenamento=armazenamento_dos_jobs,
                relogio=relogio,
            ),
            relogio,
            busca_por_minuto,
            tempo_maximo_da_busca_s,
        )
    )
    app.include_router(v1)
    if pasta_web.is_dir():
        app.mount("/", _FrontComEnderecos(directory=pasta_web, html=True))
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
        catalogo=CatalogoFirestore(firestore.Client(project=_projeto)),
        indice=(
            AgentRetrieval(ConfigDaBusca.do_ambiente(os.environ), transporte_http())
            if "BUSCA_COLECAO" in os.environ
            else None
        ),
    )
else:
    app = criar_app()
