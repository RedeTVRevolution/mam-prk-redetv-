import os
import threading
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from starlette.exceptions import HTTPException as ExcecaoHttp
from starlette.responses import Response
from starlette.types import Scope

from api.acessos import AcessosNaAuditoria
from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.aprovacao import criar_rotas_da_aprovacao
from api.auditoria import (
    RepositorioDeAuditoria,
    RepositorioDeAuditoriaEmMemoria,
    criar_rotas_da_auditoria,
)
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
from api.busca import Busca, EmbeddingDaConsulta, Ranking, RankingEmOrdem
from api.busca_na_nuvem import adaptadores_da_busca
from api.catalogo import Catalogo, CatalogoEmMemoria
from api.catalogo_de_correcoes import CatalogoDeCorrecoes
from api.catalogo_de_correcoes import catalogo as catalogo_de_correcoes
from api.chaves import (
    Mac,
    RepositorioDeChaves,
    VerificadorDeChaveDeApi,
)
from api.comparar_passadas import criar_rotas_da_comparacao
from api.copia_bigquery import CopiaDosMomentos, copia_do_ambiente
from api.correcao_de_estado import criar_rotas_da_correcao_de_estado
from api.correcoes import (
    RepositorioDeAprovacao,
    RepositorioDeAprovacaoEmMemoria,
    RepositorioDeCorrecoes,
    RepositorioDeCorrecoesEmMemoria,
)
from api.custo_do_painel import FonteDeCusto, faturamento_do_ambiente
from api.decupagem import Decupagem
from api.embedding_do_quadro import EmbeddingDoQuadro, embedding_da_busca
from api.entendimento_da_consulta import ModelArmor
from api.eventos_de_uso import (
    Eventos,
    EventosEmSegundoPlano,
    SemEventos,
    quem_do_chamador,
    registrar,
)
from api.eventos_do_job import eventos_do_ambiente
from api.fusao_de_pessoas import criar_rotas_da_fusao
from api.gemini import Chamada, ErroHttp, Transporte
from api.idempotencia import RepositorioDeIdempotencia
from api.indexacao import reindexar
from api.indice_da_busca import IndiceDaBusca, IndiceEmMemoria
from api.jobs import (
    TAMANHO_MAXIMO_PADRAO_BYTES,
    Armazenamento,
    ArmazenamentoIndisponivel,
    Job,
    RepositorioDeJobs,
    RepositorioIndisponivel,
    ServicoIndisponivel,
    TipoNaoSuportado,
    _chave_com_algum,
    _exige_aprovar,
    agora_utc,
    criar_rotas,
    papeis_da_pessoa,
)
from api.lixeira import (
    ArquivosDoJob,
    ArquivosEmMemoria,
    criar_rotas_da_lixeira,
    sem_job_na_lixeira,
)
from api.lixeira_do_catalogo import (
    FotosDeReferencia,
    FotosEmMemoria,
    criar_rotas_da_lixeira_do_catalogo,
)
from api.mac_kms import mac_do_ambiente
from api.marcas import CatalogoDeMarcas, CatalogoDeMarcasEmMemoria
from api.nuvem import (
    ArmazenamentoStorage,
    ArquivosNoStorage,
    CatalogoDeMarcasFirestore,
    CatalogoFirestore,
    ContasIdentityPlatform,
    DisparoPeloWorkflows,
    JanelasStorage,
    ReferenciasStorage,
    RepositorioDeAprovacaoFirestore,
    RepositorioDeAuditoriaFirestore,
    RepositorioDeChavesFirestore,
    RepositorioDeCorrecoesFirestore,
    RepositorioDeIdempotenciaFirestore,
    RepositorioDePapeisFirestore,
    RepositorioDeRevisaoFirestore,
    RepositorioDeSugestoesFirestore,
    RepositorioFirestore,
    TiposDeObjetoFirestore,
)
from api.painel import AcessosAoPainel, criar_rotas_do_painel
from api.papeis import (
    Papel,
    Permissao,
    RepositorioDePapeis,
    RepositorioDePapeisEmMemoria,
    admins_de,
    permissoes_de,
)
from api.passadas import (
    LeituraDePassadas,
    PassadasEmMemoria,
    PassadasStorage,
    criar_rotas_das_passadas,
)
from api.programas import PERFIS
from api.progresso_das_janelas import JanelasDoJob
from api.purga import LOGIN_RECENTE_PADRAO, Purga, criar_rotas_da_purga
from api.qualidade_do_painel import QualidadeDoPainel, QualidadeReal
from api.relatorio_de_marcas import (
    ConsultaDeInsercoes,
    criar_rotas_das_marcas,
)
from api.relatorio_de_marcas import consulta_do_ambiente as marcas_do_ambiente
from api.renomeacao_de_pessoas import criar_rotas_da_renomeacao
from api.reprocessamento import (
    DisparoDoWorkflow,
    DisparoIndisponivel,
    criar_rotas_do_reprocessamento,
)
from api.resumos_de_uso import ResumosDeUso, resumos_do_ambiente
from api.revisao import (
    LIMITE_DE_INATIVIDADE_S,
    RepositorioDeRevisao,
    RepositorioDeRevisaoEmMemoria,
    criar_rotas_da_revisao,
)
from api.rota_da_busca import (
    CONSULTAS_POR_MINUTO,
    LIMITES_DA_IMAGEM,
    TEMPO_MAXIMO_S,
    LimitesDaImagem,
    criar_rotas_da_busca,
)
from api.rotas_das_chaves import (
    ChaveIndisponivel,
    MacIndisponivel,
    criar_rotas_das_chaves,
)
from api.rotas_do_catalogo import criar_rotas_do_catalogo
from api.sugestoes import (
    RepositorioDeSugestoes,
    RepositorioDeSugestoesEmMemoria,
    criar_rotas_da_contagem,
)
from api.taxa_de_correcao import criar_rotas_da_qualidade
from api.tempo_de_tela import (
    ConsultaDeMomentos,
    consulta_do_ambiente,
    criar_rotas_do_tempo_de_tela,
)
from api.tipos_de_objeto import (
    TiposDeObjeto,
    TiposDeObjetoEmMemoria,
    criar_rotas_dos_tipos_de_objeto,
)
from api.usuarios import (
    ContasDeUsuario,
    ContasIndisponiveis,
    criar_rotas_dos_usuarios,
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


# A rota da chamada de API que não casou com nenhuma rota da API.
ROTA_DESCONHECIDA = "(sem rota)"

# Um login mais velho que isto já foi visto pela sessão: não é evento novo.
LOGIN_NOVO = timedelta(minutes=5)


class _LoginsPublicados:
    """Os últimos logins já publicados por esta instância, para não repetir o evento
    a cada recarga. Outra instância pode repetir: o id é o mesmo, e quem lê a tabela
    descarta a repetida."""

    def __init__(self, tamanho: int = 1000) -> None:
        self._vistos: dict[str, None] = {}
        self._tamanho = tamanho
        self._trava = threading.Lock()

    def novo(self, id_do_login: str) -> bool:
        with self._trava:
            if id_do_login in self._vistos:
                return False
            self._vistos[id_do_login] = None
            if len(self._vistos) > self._tamanho:
                self._vistos.pop(next(iter(self._vistos)))
            return True


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
    auditoria: RepositorioDeAuditoria | None = None,
    contas: ContasDeUsuario | None = None,
    repositorio_de_chaves: RepositorioDeChaves | None = None,
    mac: Mac | None = None,
    arquivos: ArquivosDoJob | None = None,
    revisao: RepositorioDeRevisao | None = None,
    disparo: DisparoDoWorkflow | None = None,
    janelas: JanelasDoJob | None = None,
    catalogo: Catalogo | None = None,
    marcas: CatalogoDeMarcas | None = None,
    fotos_de_referencia: FotosDeReferencia | None = None,
    sugestoes: RepositorioDeSugestoes | None = None,
    indice: IndiceDaBusca | None = None,
    copia: CopiaDosMomentos | None = None,
    embedding: EmbeddingDoQuadro | None = None,
    embedding_da_consulta: EmbeddingDaConsulta | None = None,
    tipos_de_objeto: TiposDeObjeto | None = None,
    tempo_de_tela: ConsultaDeMomentos | None = None,
    resumos_de_uso: ResumosDeUso | None = None,
    qualidade_do_painel: QualidadeDoPainel | None = None,
    faturamento: FonteDeCusto | None = None,
    relatorio_de_marcas: ConsultaDeInsercoes | None = None,
    passadas: LeituraDePassadas | None = None,
    transporte_da_consulta: Transporte | None = None,
    armor: ModelArmor | None = None,
    ranking: Ranking | None = None,
    busca_por_minuto: int = CONSULTAS_POR_MINUTO,
    tempo_maximo_da_busca_s: float = TEMPO_MAXIMO_S,
    limites_da_imagem: LimitesDaImagem = LIMITES_DA_IMAGEM,
    tamanho_maximo_bytes: int = TAMANHO_MAXIMO_PADRAO_BYTES,
    limite_de_inatividade_s: float = LIMITE_DE_INATIVIDADE_S,
    login_recente: timedelta = LOGIN_RECENTE_PADRAO,
    relogio: Callable[[], datetime] = agora_utc,
    rotas_do_push: APIRouter | None = None,
    idempotencia: RepositorioDeIdempotencia | None = None,
    eventos: Eventos | None = None,
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
    # Com repositório e chave MAC, a API confere as chaves emitidas por ela mesma.
    if chaves is None and repositorio_de_chaves and mac:
        chaves = VerificadorDeChaveDeApi(repositorio_de_chaves, mac)
    app.state.chaves = chaves or _SemChaves()
    app.state.papeis = papeis or RepositorioDePapeisEmMemoria()
    app.state.admins = admins_de(admins_emergencia)
    publicador = eventos or SemEventos()
    logins_publicados = _LoginsPublicados()

    # Antes da autenticação na ordem de registro, logo depois dela na execução: o
    # chamador já está em `request.state`.
    async def _registrar_chamada_de_api(
        request: Request, seguinte: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        resposta = await seguinte(request)
        chamador = getattr(request.state, "chamador", None)
        if isinstance(chamador, Sistema):
            # O caminho da rota, com `{job_id}` em vez do valor, e com o prefixo.
            rota = getattr(request.scope.get("route"), "path", None)
            if rota is not None and not rota.startswith(PREFIXO_PROTEGIDO):
                rota = PREFIXO_PROTEGIDO + rota
            await run_in_threadpool(
                registrar,
                publicador,
                "chamada_de_api",
                quem_do_chamador(chamador),
                relogio(),
                metodo=request.method,
                # Sem rota casada (404), o caminho levaria os valores: vai o marcador.
                rota=rota or ROTA_DESCONHECIDA,
                status=resposta.status_code,
            )
        return resposta

    app.middleware("http")(_registrar_chamada_de_api)
    app.middleware("http")(exigir_autenticacao)

    def _registrar_login(pessoa: Usuario) -> None:
        """O que a API vê do login: a primeira chamada de `/eu` depois dele, que o front
        faz ao abrir a sessão. O id vem do uid e do momento do login, então a recarga da
        página não vira outro evento."""
        entrou = pessoa.login_em
        if entrou is None or relogio() - entrou > LOGIN_NOVO:
            return
        id_do_login = uuid.uuid5(
            uuid.NAMESPACE_URL, f"login:{pessoa.uid}:{entrou.isoformat()}"
        ).hex
        if logins_publicados.novo(id_do_login):
            registrar(
                publicador,
                "login",
                quem_do_chamador(pessoa),
                entrou,
                id=id_do_login,
            )

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
        _registrar_login(chamador)
        efetivos = papeis_da_pessoa(request, chamador)
        return UsuarioComPapeis(
            **chamador.model_dump(),
            papeis=efetivos,
            permissoes=sorted(permissoes_de(efetivos)),
        )

    # A chave precisa poder enviar ou ler; só cancelar não tem o que escolher.
    @v1.get("/programas", dependencies=[Depends(_chave_com_algum("criar", "ler"))])
    def programas() -> list[str]:
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
    tipos_dos_objetos = tipos_de_objeto or TiposDeObjetoEmMemoria()
    catalogo_de_pessoas = catalogo or CatalogoEmMemoria()
    catalogo_de_marcas = marcas or CatalogoDeMarcasEmMemoria()
    repositorio_de_auditoria = auditoria or RepositorioDeAuditoriaEmMemoria()
    repositorio_de_sugestoes = sugestoes or RepositorioDeSugestoesEmMemoria()
    repositorio_da_revisao = revisao or RepositorioDeRevisaoEmMemoria()
    repositorio_de_aprovacao = aprovacao or RepositorioDeAprovacaoEmMemoria()
    v1.include_router(
        criar_rotas(
            repositorio_de_jobs,
            armazenamento_dos_jobs,
            tamanho_maximo_bytes,
            relogio,
            repositorio_de_correcoes,
            repositorio_de_aprovacao,
            catalogo_de_pessoas,
            catalogo_de_marcas,
            repositorio_de_sugestoes,
            lambda job: reindexar(
                job,
                repositorio_de_jobs,
                armazenamento_dos_jobs,
                repositorio_de_correcoes,
                indice_da_busca,
                relogio,
                copia,
                embedding,
                armazenamento_dos_jobs,
                tipos_de_objeto=tipos_dos_objetos,
                pessoas=catalogo_de_pessoas.obter,
            ),
            AcessosNaAuditoria(repositorio_de_auditoria, relogio),
            tipos_dos_objetos.conhecidos,
            idempotencia,
            publicador,
        )
    )
    leitura_de_passadas = passadas or PassadasEmMemoria()
    v1.include_router(
        criar_rotas_das_passadas(repositorio_de_jobs, leitura_de_passadas)
    )
    v1.include_router(
        criar_rotas_da_comparacao(
            repositorio_de_jobs,
            leitura_de_passadas,
            lambda job_id: Decupagem.model_validate_json(
                b"".join(armazenamento_dos_jobs.abrir_decupagem(job_id))
            ),
        )
    )
    v1.include_router(criar_rotas_dos_tipos_de_objeto(tipos_dos_objetos))
    v1.include_router(criar_rotas_da_contagem(repositorio_de_sugestoes, _exige_aprovar))

    def _reindexar_para_a_renomeacao(job: Job) -> bool:
        indexacao = reindexar(
            job,
            repositorio_de_jobs,
            armazenamento_dos_jobs,
            repositorio_de_correcoes,
            indice_da_busca,
            relogio,
            copia,
            embedding,
            armazenamento_dos_jobs,
            tipos_de_objeto=tipos_dos_objetos,
            pessoas=catalogo_de_pessoas.obter,
        )
        return indexacao is not None and indexacao.estado == "indexado"

    def _rotas_das_pessoas(descartar: Callable[[], None]) -> APIRouter:
        """Fundir (#209) e renomear em todos os vídeos (#263), sob `/catalogo`."""
        rotas = APIRouter()
        rotas.include_router(
            criar_rotas_da_fusao(
                catalogo_de_pessoas,
                repositorio_de_jobs,
                repositorio_de_correcoes,
                armazenamento_dos_jobs,
                fotos_de_referencia or FotosEmMemoria(),
                repositorio_de_auditoria,
                relogio,
                descartar,
            )
        )
        rotas.include_router(
            criar_rotas_da_renomeacao(
                catalogo_de_pessoas,
                repositorio_de_jobs,
                repositorio_de_correcoes,
                armazenamento_dos_jobs,
                repositorio_de_auditoria,
                relogio,
                _reindexar_para_a_renomeacao,
                descartar,
            )
        )
        return rotas

    v1.include_router(
        criar_rotas_do_catalogo(
            catalogo_de_pessoas,
            catalogo_de_marcas,
            relogio,
            _rotas_das_pessoas,
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
                embedding=embedding_da_consulta,
            ),
            relogio,
            busca_por_minuto,
            tempo_maximo_da_busca_s,
            limites_da_imagem,
            publicador,
        )
    )
    v1.include_router(criar_rotas_da_auditoria(repositorio_de_auditoria))
    v1.include_router(
        criar_rotas_do_painel(
            resumos_de_uso,
            contas or ContasIndisponiveis(),
            AcessosAoPainel(repositorio_de_auditoria, relogio),
            qualidade_do_painel
            or QualidadeReal(
                repositorio_de_jobs,
                armazenamento_dos_jobs,
                repositorio_de_correcoes,
                repositorio_da_revisao,
            ),
            faturamento,
            repositorio_de_jobs,
        )
    )
    v1.include_router(
        criar_rotas_dos_usuarios(
            contas or ContasIndisponiveis(),
            app.state.papeis,
            repositorio_de_auditoria,
            lambda: app.state.admins,
            relogio,
        )
    )
    v1.include_router(
        criar_rotas_das_chaves(
            repositorio_de_chaves or ChaveIndisponivel(),
            mac or MacIndisponivel(),
            repositorio_de_auditoria,
            relogio,
        )
    )
    v1.include_router(
        criar_rotas_da_aprovacao(
            repositorio_de_aprovacao,
            repositorio_de_auditoria,
            relogio,
        )
    )
    v1.include_router(
        criar_rotas_do_reprocessamento(
            repositorio_de_jobs,
            repositorio_de_auditoria,
            disparo or DisparoIndisponivel(),
            relogio,
            janelas,
        )
    )
    v1.include_router(
        criar_rotas_da_lixeira(
            repositorio_de_jobs,
            repositorio_de_correcoes,
            arquivos or ArquivosEmMemoria(),
            repositorio_de_auditoria,
            relogio,
            catalogo_de_pessoas,
            catalogo_de_marcas,
        )
    )
    v1.include_router(
        criar_rotas_da_lixeira_do_catalogo(
            catalogo_de_pessoas,
            catalogo_de_marcas,
            repositorio_de_jobs,
            repositorio_de_correcoes,
            armazenamento_dos_jobs,
            fotos_de_referencia or FotosEmMemoria(),
            repositorio_de_auditoria,
            relogio,
            login_recente,
        )
    )
    v1.include_router(
        criar_rotas_da_purga(
            Purga(
                repositorio_de_jobs,
                repositorio_de_correcoes,
                arquivos or ArquivosEmMemoria(),
                indice_da_busca,
                repositorio_de_auditoria,
                relogio,
            ),
            repositorio_de_jobs,
            relogio,
            login_recente,
        )
    )
    v1.include_router(
        criar_rotas_da_correcao_de_estado(
            repositorio_de_jobs,
            repositorio_de_auditoria,
            armazenamento_dos_jobs,
            relogio,
        )
    )
    v1.include_router(
        criar_rotas_da_revisao(
            repositorio_de_jobs,
            repositorio_da_revisao,
            relogio,
            limite_de_inatividade_s,
        )
    )
    v1.include_router(
        criar_rotas_da_qualidade(
            repositorio_de_jobs,
            armazenamento_dos_jobs,
            repositorio_de_correcoes,
            repositorio_da_revisao,
        )
    )
    v1.include_router(criar_rotas_do_tempo_de_tela(tempo_de_tela, repositorio_de_jobs))
    v1.include_router(criar_rotas_das_marcas(relatorio_de_marcas, repositorio_de_jobs))
    # Vale para toda rota com `{job_id}`: o vídeo na lixeira some para quem não é Administrador.
    app.include_router(
        v1, dependencies=[Depends(sem_job_na_lixeira(repositorio_de_jobs))]
    )
    # Fora de `/v1`, com o token do Pub/Sub em vez do de pessoa ou sistema.
    if rotas_do_push is not None:
        app.include_router(rotas_do_push)
    if pasta_web.is_dir():
        app.mount("/", _FrontComEnderecos(directory=pasta_web, html=True))
    return app


# No Cloud Run, o Terraform define o projeto; fora dele, a API nega todo token.
_projeto = os.environ.get("GCP_PROJECT_ID")
if _projeto:
    _adaptadores = adaptadores_da_busca(os.environ)
    _busca = (
        ConfigDaBusca.do_ambiente(os.environ) if "BUSCA_COLECAO" in os.environ else None
    )
    _embedding = embedding_da_busca(_busca)
    app = criar_app(
        VerificadorIdentityPlatform(_projeto),
        RepositorioFirestore(firestore.Client(project=_projeto)),
        ArmazenamentoStorage(
            ClienteStorage(project=_projeto),
            os.environ["BUCKET_QUARENTENA"],
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
            bucket_de_referencias=os.environ["BUCKET_REFERENCIAS"],
        ),
        papeis=RepositorioDePapeisFirestore(firestore.Client(project=_projeto)),
        admins_emergencia=os.environ.get("ADMINS_EMERGENCIA"),
        correcoes=RepositorioDeCorrecoesFirestore(firestore.Client(project=_projeto)),
        aprovacao=RepositorioDeAprovacaoFirestore(firestore.Client(project=_projeto)),
        auditoria=RepositorioDeAuditoriaFirestore(firestore.Client(project=_projeto)),
        contas=ContasIdentityPlatform(_projeto),
        # O evento de uso sai fora da resposta: o Pub/Sub lento não atrasa a ação.
        eventos=EventosEmSegundoPlano(eventos_do_ambiente(os.environ)),
        # A chave MAC é a do Cloud KMS (KMS_CHAVE_MAC); sem ela, a simulada (como no
        # `make emitir-chave`). Sem nenhuma, emitir dá 503 e a API não aceita chave de
        # sistema; listar e revogar funcionam.
        idempotencia=RepositorioDeIdempotenciaFirestore(
            firestore.Client(project=_projeto)
        ),
        repositorio_de_chaves=RepositorioDeChavesFirestore(
            firestore.Client(project=_projeto)
        ),
        arquivos=ArquivosNoStorage(
            ClienteStorage(project=_projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        mac=mac_do_ambiente(os.environ),
        revisao=RepositorioDeRevisaoFirestore(firestore.Client(project=_projeto)),
        login_recente=timedelta(
            minutes=float(os.environ.get("PURGA_LOGIN_RECENTE_MIN") or 0)
            or LOGIN_RECENTE_PADRAO / timedelta(minutes=1)
        ),
        limite_de_inatividade_s=float(
            os.environ.get("REVISAO_INATIVIDADE_S") or LIMITE_DE_INATIVIDADE_S
        ),
        disparo=DisparoPeloWorkflows(
            _projeto, os.environ["WORKFLOW_REGIAO"], os.environ["WORKFLOW_VALIDACAO"]
        ),
        janelas=JanelasStorage(
            ClienteStorage(project=_projeto), os.environ["BUCKET_ACEITOS"]
        ),
        catalogo=CatalogoFirestore(firestore.Client(project=_projeto)),
        marcas=CatalogoDeMarcasFirestore(firestore.Client(project=_projeto)),
        fotos_de_referencia=ReferenciasStorage(
            ClienteStorage(project=_projeto), os.environ["BUCKET_REFERENCIAS"]
        ),
        sugestoes=RepositorioDeSugestoesFirestore(firestore.Client(project=_projeto)),
        indice=AgentRetrieval(_busca, transporte_http()) if _busca else None,
        copia=copia_do_ambiente(os.environ),
        embedding=_embedding,
        embedding_da_consulta=_embedding,
        tipos_de_objeto=TiposDeObjetoFirestore(firestore.Client(project=_projeto)),
        limites_da_imagem=LimitesDaImagem(
            max_bytes=int(
                os.environ.get("BUSCA_IMAGEM_MAX_BYTES") or LimitesDaImagem.max_bytes
            ),
            max_pixels=int(
                os.environ.get("BUSCA_IMAGEM_MAX_PIXELS") or LimitesDaImagem.max_pixels
            ),
        ),
        tempo_de_tela=consulta_do_ambiente(os.environ),
        resumos_de_uso=resumos_do_ambiente(os.environ),
        faturamento=faturamento_do_ambiente(os.environ),
        relatorio_de_marcas=marcas_do_ambiente(os.environ),
        passadas=PassadasStorage(
            ClienteStorage(project=_projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        transporte_da_consulta=_adaptadores.transporte_da_consulta,
        armor=_adaptadores.armor,
        ranking=_adaptadores.ranking,
    )
else:
    app = criar_app()
