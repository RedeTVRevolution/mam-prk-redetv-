import os
import threading
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as ExcecaoHttp
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from api.acessos import AcessosNaAuditoria
from api.agent_retrieval import (
    AgentRetrieval,
    ConfigDaBusca,
    aquecer_o_indice,
    transporte_http,
)
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
from api.bancos import cliente_da_colecao, cliente_do_firestore
from api.busca import (
    Busca,
    ListasDaBusca,
    Ranking,
    RankingEmOrdem,
)
from api.busca_na_nuvem import adaptadores_da_busca, aquecer_na_partida
from api.cache_curto import CacheCurto
from api.catalogo import Catalogo, CatalogoEmMemoria, CopiaCurta
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
from api.dados_da_purga import dados_do_ambiente
from api.decupagem import Decupagem
from api.edicao_do_video import criar_rotas_da_edicao
from api.eventos_de_uso import (
    Eventos,
    SemEventos,
    quem_do_chamador,
    registrar,
)
from api.eventos_do_job import eventos_do_ambiente
from api.fusao_de_pessoas import criar_rotas_da_fusao
from api.gemini import Chamada, ErroHttp, Transporte
from api.idempotencia import RepositorioDeIdempotencia
from api.indice_da_busca import IndiceDaBusca, IndiceEmMemoria
from api.jobs import (
    TAMANHO_MAXIMO_PADRAO_BYTES,
    Armazenamento,
    ArmazenamentoIndisponivel,
    DisparoDaIndexacao,
    DisparoDaIndexacaoIndisponivel,
    RepositorioDeJobs,
    RepositorioIndisponivel,
    ServicoIndisponivel,
    TipoNaoSuportado,
    _chave_com_algum,
    aceita_gzip,
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
from api.lixeira_na_leitura import (
    VersaoDaLixeira,
    VersaoDaLixeiraEmMemoria,
    VersaoDaLixeiraFirestore,
)
from api.log_estruturado import configurar as configurar_o_log
from api.mac_kms import mac_do_ambiente
from api.marcas import CatalogoDeMarcas, CatalogoDeMarcasEmMemoria
from api.nuvem import (
    COLECAO_DA_AUDITORIA,
    COLECAO_DE_CHAVES,
    COLECAO_DE_PAPEIS,
    ArmazenamentoStorage,
    ArquivosNoStorage,
    CatalogoDeMarcasFirestore,
    CatalogoFirestore,
    ContasIdentityPlatform,
    DisparoDaIndexacaoNoCloudRun,
    DisparoPeloWorkflows,
    JanelasStorage,
    ListasDaBuscaFirestore,
    ProgramasFirestore,
    ReferenciasStorage,
    RepositorioDeAprovacaoFirestore,
    RepositorioDeAuditoriaFirestore,
    RepositorioDeChavesFirestore,
    RepositorioDeCorrecoesFirestore,
    RepositorioDeIdempotenciaFirestore,
    RepositorioDePapeisFirestore,
    RepositorioDeRevisaoFirestore,
    RepositorioFirestore,
    TiposDeObjetoFirestore,
    listagem_por_mes_do_ambiente,
)
from api.orcamento_de_escrita import OrcamentoFirestore
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
from api.programas import (
    NomesDosProgramas,
    ProgramasEmMemoria,
    RepositorioDeProgramas,
)
from api.progresso_das_janelas import JanelasDoJob
from api.purga import LOGIN_RECENTE_PADRAO, Purga, criar_rotas_da_purga
from api.qualidade_do_painel import QualidadeDoPainel, QualidadeReal
from api.relatorio_de_marcas import ConsultaComCache as MarcasComCache
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
from api.revisao_do_painel import (
    RepositorioDeRevisaoEspelhado,
    RevisaoEmMemoria,
    TempoDeRevisao,
    revisao_do_ambiente,
    tabela_do_ambiente,
)
from api.rota_da_busca import (
    CONSULTAS_POR_MINUTO,
    LIMITES_DA_IMAGEM,
    TEMPO_MAXIMO_S,
    LimitesDaImagem,
    consultas_por_minuto_do_ambiente,
    criar_rotas_da_busca,
)
from api.rotas_das_chaves import (
    ChaveIndisponivel,
    MacIndisponivel,
    criar_rotas_das_chaves,
)
from api.rotas_do_catalogo import criar_rotas_do_catalogo
from api.rotas_dos_programas import criar_rotas_dos_programas
from api.taxa_de_correcao import criar_rotas_da_qualidade
from api.taxa_do_painel import LeitorDaTaxa, TaxaEmMemoria, taxa_do_ambiente
from api.tempo_de_tela import ConsultaComCache as TempoDeTelaComCache
from api.tempo_de_tela import (
    ConsultaDeMomentos,
    consulta_do_ambiente,
    criar_rotas_do_tempo_de_tela,
)
from api.teste_de_carga import aceita_teste_de_carga_do_ambiente
from api.texto_como_dado import conferir_ids_e_consultas
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
CACHE_DOS_ASSETS = "public, max-age=31536000, immutable"


class _SemVerificador:
    """Sem projeto do Identity Platform (testes e máquina local): nega tudo."""

    def verificar(self, token: str) -> Usuario:
        raise TokenInvalido


class _SemChaves:
    """Sem adaptador de chaves de API: recusa toda chave."""

    def verificar(self, chave: str) -> Sistema:
        raise ChaveInvalida


class _SemModelo:
    """Sem modelo ligado: a busca por imagem fica indisponível."""

    def gerar(self, chamada: Chamada) -> str:
        raise ErroHttp(503)


class _FrontComEnderecos(StaticFiles):
    """O front tem endereço por tela (`/video/{id}`): fora de `/v1`, o que não é arquivo
    do build devolve o `index.html`, e o roteador do front decide a tela."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            resposta = await super().get_response(path, scope)
        except ExcecaoHttp as erro:
            ultimo = path.rsplit("/", 1)[-1]
            if erro.status_code != 404 or "." in ultimo:
                raise
            if path == "v1" or path.startswith("v1/"):
                raise
            resposta = await super().get_response("index.html", scope)
            resposta.headers["Cache-Control"] = "no-cache"
            return resposta
        # `assets/*` leva o hash no nome (#558); o resto revalida pelo ETag a cada visita,
        # para um deploy novo nunca deixar um `index.html` velho em cache.
        resposta.headers["Cache-Control"] = (
            CACHE_DOS_ASSETS if path.startswith("assets/") else "no-cache"
        )
        return resposta


class _GZipQueRespeitaQZero(GZipMiddleware):
    """O do Starlette só procura "gzip" no texto: `gzip;q=0` ainda comprimiria."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not aceita_gzip(
            Headers(scope=scope).get("accept-encoding", "")
        ):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


# Cabeçalhos de segurança de toda resposta (#372). O Storage está em `img-src` (capas e
# quadros), `media-src` (o vídeo do Visualizador) e `connect-src` (o service worker das
# capas e o envio); o Identity Platform, no login e na renovação do token.
_STORAGE = "https://storage.googleapis.com"
CABECALHOS_DE_SEGURANCA = {
    "Content-Security-Policy": (
        "default-src 'self'; "
        "style-src-elem 'self' 'unsafe-inline'; "
        f"img-src 'self' {_STORAGE}; "
        f"media-src 'self' {_STORAGE}; "
        f"connect-src 'self' {_STORAGE} https://identitytoolkit.googleapis.com "
        "https://securetoken.googleapis.com; "
        "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000",
}

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
    disparo_da_indexacao: DisparoDaIndexacao | None = None,
    janelas: JanelasDoJob | None = None,
    catalogo: Catalogo | None = None,
    marcas: CatalogoDeMarcas | None = None,
    programas: RepositorioDeProgramas | None = None,
    fotos_de_referencia: FotosDeReferencia | None = None,
    indice: IndiceDaBusca | None = None,
    copia: CopiaDosMomentos | None = None,
    tipos_de_objeto: TiposDeObjeto | None = None,
    tempo_de_tela: ConsultaDeMomentos | None = None,
    resumos_de_uso: ResumosDeUso | None = None,
    qualidade_do_painel: QualidadeDoPainel | None = None,
    faturamento: FonteDeCusto | None = None,
    tempo_de_revisao: TempoDeRevisao | None = None,
    taxa_de_correcao: LeitorDaTaxa | None = None,
    relatorio_de_marcas: ConsultaDeInsercoes | None = None,
    cache_do_painel: CacheCurto | None = None,
    cache_da_lista: CacheCurto | None = None,
    passadas: LeituraDePassadas | None = None,
    transporte_da_consulta: Transporte | None = None,
    ranking: Ranking | None = None,
    listas_da_busca: ListasDaBusca | None = None,
    busca_por_minuto: int = CONSULTAS_POR_MINUTO,
    tempo_maximo_da_busca_s: float = TEMPO_MAXIMO_S,
    limites_da_imagem: LimitesDaImagem = LIMITES_DA_IMAGEM,
    aceita_teste_de_carga: bool = False,
    tamanho_maximo_bytes: int = TAMANHO_MAXIMO_PADRAO_BYTES,
    limite_de_inatividade_s: float = LIMITE_DE_INATIVIDADE_S,
    login_recente: timedelta = LOGIN_RECENTE_PADRAO,
    relogio: Callable[[], datetime] = agora_utc,
    rotas_do_push: APIRouter | None = None,
    idempotencia: RepositorioDeIdempotencia | None = None,
    eventos: Eventos | None = None,
    pasta_web: Path = PASTA_WEB,
    apagar_dados_da_purga: Callable[[str], None] | None = None,
    versao_da_lixeira: VersaoDaLixeira | None = None,
) -> FastAPI:
    app = FastAPI(title="MAM RedeTV", dependencies=[Depends(conferir_ids_e_consultas)])

    @app.exception_handler(ServicoIndisponivel)
    def _indisponivel(_request: Request, _erro: ServicoIndisponivel) -> JSONResponse:
        return JSONResponse({"detail": "Serviço indisponível"}, status_code=503)

    @app.exception_handler(TipoNaoSuportado)
    def _tipo_errado(_request: Request, _erro: TipoNaoSuportado) -> JSONResponse:
        return JSONResponse({"detail": "Só video/mp4"}, status_code=415)

    # O erro que ninguém tratou não passa pelos middlewares: quem responde é o
    # `ServerErrorMiddleware`, por fora deles, e o 500 sairia sem os cabeçalhos de
    # segurança (#372). A exceção continua subindo para o log.
    @app.exception_handler(Exception)
    def _erro_interno(_request: Request, _erro: Exception) -> PlainTextResponse:
        return PlainTextResponse(
            "Internal Server Error", status_code=500, headers=CABECALHOS_DE_SEGURANCA
        )

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

    # O mais interno dos middlewares: comprime a partir de 1 KB, nível 6 (#558). Por dentro dos
    # `@app.middleware("http")`, vê a resposta inteira: por fora, eles a entregariam em pedaços
    # (`more_body=True`) e o Starlette ignoraria o `minimum_size`.
    app.add_middleware(_GZipQueRespeitaQZero, minimum_size=1024, compresslevel=6)
    app.middleware("http")(_registrar_chamada_de_api)
    app.middleware("http")(exigir_autenticacao)

    # O último registrado é o mais externo: pega também o 401 da autenticação e os erros
    # que viram resposta dentro do app; o 500 de exceção não tratada é o `_erro_interno`.
    async def _cabecalhos_de_seguranca(
        request: Request, seguinte: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        resposta = await seguinte(request)
        resposta.headers.update(CABECALHOS_DE_SEGURANCA)
        return resposta

    app.middleware("http")(_cabecalhos_de_seguranca)

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
    # O `operation_id` de antes do #338 (a função não pode se chamar `programas`, o
    # nome do parâmetro de `criar_app`).
    @v1.get(
        "/programas",
        dependencies=[Depends(_chave_com_algum("criar", "ler"))],
        operation_id="programas_v1_programas_get",
    )
    def lista_de_programas() -> list[str]:
        """Os programas cadastrados, para o envio escolher."""
        return sorted(NomesDosProgramas(repositorio_de_programas))

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
    # Avança a cada envio, restauração, purga e fusão do catálogo (#591).
    versao_da_lixeira = versao_da_lixeira or VersaoDaLixeiraEmMemoria()
    repositorio_de_programas = programas or ProgramasEmMemoria()
    repositorio_de_auditoria = auditoria or RepositorioDeAuditoriaEmMemoria()
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
            repositorio_de_programas,
            disparo_da_indexacao or DisparoDaIndexacaoIndisponivel(),
            AcessosNaAuditoria(repositorio_de_auditoria, relogio),
            idempotencia,
            publicador,
            cache_da_lista,
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

    # Uma cópia das pessoas para o autocompletar e para a busca resolver nomes.
    copia_das_pessoas = CopiaCurta(catalogo_de_pessoas.todas, relogio)

    def _rotas_das_pessoas(descartar: Callable[[], None]) -> APIRouter:
        """Fundir (#209) e renomear em todos os vídeos (#263), sob `/catalogo`."""
        rotas = APIRouter()

        def ao_fundir() -> None:
            descartar()
            versao_da_lixeira.avancar()

        rotas.include_router(
            criar_rotas_da_fusao(
                catalogo_de_pessoas,
                repositorio_de_jobs,
                repositorio_de_correcoes,
                armazenamento_dos_jobs,
                fotos_de_referencia or FotosEmMemoria(),
                repositorio_de_auditoria,
                relogio,
                ao_fundir,
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
            copia_das_pessoas,
        )
    )
    v1.include_router(
        criar_rotas_dos_programas(
            repositorio_de_programas,
            catalogo_de_pessoas,
            repositorio_de_jobs,
            repositorio_de_auditoria,
            relogio,
            disparo_da_indexacao or DisparoDaIndexacaoIndisponivel(),
            copia_das_pessoas.descartar,
        )
    )
    v1.include_router(
        criar_rotas_da_busca(
            Busca(
                transporte=transporte_da_consulta or _SemModelo(),
                catalogo=catalogo_de_pessoas,
                indice=indice_da_busca,
                ranking=ranking or RankingEmOrdem(),
                repositorio=repositorio_de_jobs,
                armazenamento=armazenamento_dos_jobs,
                relogio=relogio,
                copia_do_catalogo=copia_das_pessoas,
                listas=listas_da_busca,
                versao_da_lixeira=versao_da_lixeira,
                marcas=catalogo_de_marcas,
            ),
            relogio,
            busca_por_minuto,
            tempo_maximo_da_busca_s,
            limites_da_imagem,
            publicador,
            aceita_teste_de_carga,
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
                taxa_de_correcao or TaxaEmMemoria(),
                tempo_de_revisao
                or RevisaoEmMemoria(repositorio_da_revisao, repositorio_de_jobs),
            ),
            faturamento,
            repositorio_de_jobs,
            relogio,
            cache_do_painel,
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
        criar_rotas_da_edicao(
            repositorio_de_jobs,
            repositorio_de_programas,
            repositorio_de_auditoria,
            disparo_da_indexacao or DisparoDaIndexacaoIndisponivel(),
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
            indice_da_busca,
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
            copia_das_pessoas.descartar,
            versao_da_lixeira.avancar,
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
                apagar_dados=apagar_dados_da_purga,
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
    v1.include_router(
        criar_rotas_do_tempo_de_tela(
            tempo_de_tela, repositorio_de_jobs, catalogo_de_pessoas, relogio
        )
    )
    v1.include_router(
        criar_rotas_das_marcas(
            relatorio_de_marcas, repositorio_de_jobs, catalogo_de_marcas, relogio
        )
    )
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


def _revisao_espelhada(banco: firestore.Client) -> RepositorioDeRevisao:
    """O Firestore da revisão com cada medida copiada para a tabela do painel (#467); sem a
    tabela configurada, o repositório puro."""
    repositorio = RepositorioDeRevisaoFirestore(banco)
    tabela = tabela_do_ambiente(os.environ)
    return (
        repositorio
        if tabela is None
        else RepositorioDeRevisaoEspelhado(repositorio, tabela)
    )


def _com_cache[C, R](
    consulta: C | None, envolver: Callable[[C, CacheCurto], R]
) -> R | None:
    """A consulta do BigQuery com o cache curto de uma instância (#453); `None` fica `None`."""
    return envolver(consulta, CacheCurto()) if consulta else None


configurar_o_log()

if _projeto:
    _adaptadores = adaptadores_da_busca(os.environ)
    _busca = (
        ConfigDaBusca.do_ambiente(os.environ) if "BUSCA_COLECAO" in os.environ else None
    )
    _transporte_do_indice = transporte_http() if _busca else None
    app = criar_app(
        VerificadorIdentityPlatform(_projeto),
        RepositorioFirestore(
            cliente_do_firestore(_projeto),
            listagem_por_mes=listagem_por_mes_do_ambiente(os.environ),
        ),
        ArmazenamentoStorage(
            ClienteStorage(project=_projeto),
            os.environ["BUCKET_QUARENTENA"],
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        papeis=RepositorioDePapeisFirestore(
            cliente_da_colecao(_projeto, COLECAO_DE_PAPEIS)
        ),
        admins_emergencia=os.environ.get("ADMINS_EMERGENCIA"),
        correcoes=RepositorioDeCorrecoesFirestore(cliente_do_firestore(_projeto)),
        aprovacao=RepositorioDeAprovacaoFirestore(cliente_do_firestore(_projeto)),
        auditoria=RepositorioDeAuditoriaFirestore(
            cliente_da_colecao(_projeto, COLECAO_DA_AUDITORIA)
        ),
        contas=ContasIdentityPlatform(_projeto),
        # O evento de uso sai dentro da requisição, antes da resposta: o Cloud Run só dá
        # CPU durante ela. Uma tentativa, no TEMPO_DO_EVENTO_DE_USO_S; a falha vai ao log.
        eventos=eventos_do_ambiente(os.environ),
        # A chave MAC é a do Cloud KMS (KMS_CHAVE_MAC); sem ela, a simulada (como no
        # `make emitir-chave`). Sem nenhuma, emitir dá 503 e a API não aceita chave de
        # sistema; listar e revogar funcionam.
        idempotencia=RepositorioDeIdempotenciaFirestore(cliente_do_firestore(_projeto)),
        listas_da_busca=ListasDaBuscaFirestore(cliente_do_firestore(_projeto)),
        repositorio_de_chaves=RepositorioDeChavesFirestore(
            cliente_da_colecao(_projeto, COLECAO_DE_CHAVES)
        ),
        arquivos=ArquivosNoStorage(
            ClienteStorage(project=_projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        mac=mac_do_ambiente(os.environ),
        revisao=_revisao_espelhada(cliente_do_firestore(_projeto)),
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
        disparo_da_indexacao=DisparoDaIndexacaoNoCloudRun(
            _projeto, os.environ["INDEXACAO_REGIAO"], os.environ["INDEXACAO_JOB"]
        ),
        janelas=JanelasStorage(
            ClienteStorage(project=_projeto), os.environ["BUCKET_ACEITOS"]
        ),
        catalogo=CatalogoFirestore(cliente_do_firestore(_projeto)),
        marcas=CatalogoDeMarcasFirestore(cliente_do_firestore(_projeto)),
        versao_da_lixeira=VersaoDaLixeiraFirestore(cliente_do_firestore(_projeto)),
        programas=ProgramasFirestore(cliente_do_firestore(_projeto)),
        fotos_de_referencia=ReferenciasStorage(
            ClienteStorage(project=_projeto), os.environ["BUCKET_REFERENCIAS"]
        ),
        # A reindexação (em `BackgroundTasks`) e a purga (no pedido da rota) esperam a
        # cota de escrita; a busca nunca espera (`AgentRetrieval`).
        indice=(
            AgentRetrieval(
                _busca,
                _transporte_do_indice,
                tentar_no_429=True,
                orcamento=OrcamentoFirestore(cliente_do_firestore(_projeto)),
            )
            if _busca and _transporte_do_indice
            else None
        ),
        copia=copia_do_ambiente(os.environ),
        tipos_de_objeto=TiposDeObjetoFirestore(cliente_do_firestore(_projeto)),
        apagar_dados_da_purga=dados_do_ambiente(
            cliente_do_firestore(_projeto), os.environ
        ).apagar,
        busca_por_minuto=consultas_por_minuto_do_ambiente(os.environ),
        aceita_teste_de_carga=aceita_teste_de_carga_do_ambiente(os.environ),
        limites_da_imagem=LimitesDaImagem(
            max_bytes=int(
                os.environ.get("BUSCA_IMAGEM_MAX_BYTES") or LimitesDaImagem.max_bytes
            ),
            max_pixels=int(
                os.environ.get("BUSCA_IMAGEM_MAX_PIXELS") or LimitesDaImagem.max_pixels
            ),
        ),
        tempo_de_tela=_com_cache(consulta_do_ambiente(os.environ), TempoDeTelaComCache),
        resumos_de_uso=resumos_do_ambiente(os.environ),
        faturamento=faturamento_do_ambiente(os.environ),
        tempo_de_revisao=revisao_do_ambiente(os.environ),
        taxa_de_correcao=taxa_do_ambiente(os.environ),
        relatorio_de_marcas=_com_cache(marcas_do_ambiente(os.environ), MarcasComCache),
        cache_do_painel=CacheCurto(),
        passadas=PassadasStorage(
            ClienteStorage(project=_projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        transporte_da_consulta=_adaptadores.transporte_da_consulta,
        ranking=_adaptadores.ranking,
    )
    # Conexão TLS e token do índice, do embedding e da Ranking prontos antes da 1ª busca (#568).
    # Em segundo plano: não atrasa a partida nem o readiness.
    _aquecimentos: list[Callable[[], None]] = []
    if _busca and _transporte_do_indice:
        _aquecimentos.append(partial(aquecer_o_indice, _transporte_do_indice, _busca))
    if _adaptadores.aquecer:
        _aquecimentos.append(_adaptadores.aquecer)
    aquecer_na_partida(_aquecimentos)
else:
    app = criar_app()
