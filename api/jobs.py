"""Jobs da E0: modelo, portas (Firestore e Storage) e rotas `/v1/jobs`."""

import hashlib
import itertools
import json
import re
import unicodedata
import uuid
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from api.auth import (
    Chamador,
    ChamadorAutenticado,
    Escopo,
    Sistema,
    Usuario,
)
from api.catalogo import Catalogo
from api.ciclo_de_vida import JaTerminou, transitar
from api.ciclo_de_vida import cancelar as cancelar_job
from api.correcoes import (
    Autoria,
    Correcao,
    CorrecaoInexistente,
    CorrecaoJaExiste,
    ItemDaFila,
    ItemDoHistorico,
    ItemInexistente,
    NaoCandidato,
    NaoDesfazivel,
    NaoNaFila,
    NaoPendente,
    NovaCorrecao,
    NovaReaplicacao,
    NovaRecusa,
    NovaResolucao,
    NovoDesfazer,
    RepositorioDeAprovacao,
    RepositorioDeCorrecoes,
    TemposInvalidos,
    VersaoDesatualizada,
    corrigir,
    decidir,
    decupagem_entregue,
    descartar,
    desfazer,
    fila,
    historico,
    reaplicar,
    versao_do_modelo,
)
from api.decupagem import caminho_do_quadro
from api.papeis import (
    Papel,
    Permissao,
    RepositorioDePapeis,
    papeis_do_usuario,
    permissoes_de,
)
from api.programas import PERFIS

TIPO_DO_VIDEO = "video/mp4"
TAMANHO_MAXIMO_PADRAO_BYTES = 4 * 1024**3
PRAZO_DO_UPLOAD = timedelta(hours=24)
VALIDADE_DA_REPRODUCAO = timedelta(minutes=10)
# O "hoje" da data de exibição é o de Brasília, sem horário de verão desde 2019.
FUSO_DA_EMISSORA = timezone(timedelta(hours=-3))

Estado = Literal[
    "aguardando_upload",
    "validando",
    "analisando",
    "concluido",
    "falhou",
    "cancelado",
]
CodigoDeFalha = Literal[
    "formato_invalido",
    "arquivo_corrompido",
    "codec_nao_suportado",
    "duracao_excedida",
    "upload_expirado",
    "analise_falhou",
    "transcricao_falhou",
    "ocr_falhou",
]


EstadoDaIndexacao = Literal["pendente", "indexado", "falhou"]


class Indexacao(BaseModel):
    """Onde o Job está no índice da busca; uma falha dela não muda o `estado` do Job."""

    estado: EstadoDaIndexacao
    em: datetime


class Job(BaseModel):
    id: str
    nome: str
    tamanho_bytes: int
    sha256: str | None = None
    duracao_s: float | None = None
    # Cortes de câmera da validação, em ms; `None` em Job anterior à detecção.
    cortes_ms: list[int] | None = None
    # Timecode inicial da faixa `tmcd` do arquivo; `None` sem a faixa, fora do
    # formato ou em Job anterior ao campo.
    timecode_origem: str | None = None
    # Quadros por segundo do vídeo (ffprobe); `None` em Job anterior ao campo.
    taxa_de_quadros: float | None = None
    estado: Estado
    codigo_falha: CodigoDeFalha | None = None
    criado_por: str
    # E-mail de quem criou; `None` em Job de sistema e em Job anterior ao campo.
    criado_por_email: str | None = None
    sistema: str | None = None
    programa: str | None = None
    # Palavras normalizadas do nome do arquivo, para a busca por nome (o Firestore
    # não busca por trecho); vazio em Job anterior ao campo.
    palavras: list[str] = []
    # Dia em que o programa foi ao ar; `None` em Job anterior ao campo.
    data_exibicao: date | None = None
    # `None` até o Job concluir (e em Job anterior ao campo).
    indexacao: Indexacao | None = None
    criado_em: datetime
    atualizado_em: datetime

    @field_serializer("data_exibicao")
    def _data_como_texto(self, data: date | None) -> str | None:
        # O Firestore não guarda `date`; o Pydantic a lê de volta do texto ISO.
        return data.isoformat() if data else None


def palavras_do_nome(nome: str) -> list[str]:
    """Palavras do nome do arquivo, sem maiúsculas nem acentos.

    Quebra em tudo que não é letra nem dígito (`_`, `-`, `.`, espaço, parênteses...).
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", nome) if not unicodedata.combining(c)
    )
    palavras = [p for p in re.split(r"[\W_]+", sem_acento.casefold()) if p]
    return list(dict.fromkeys(palavras))


class EnviadoPor(BaseModel):
    tipo: Literal["pessoa", "sistema"]
    # O e-mail da pessoa (`None` em Job antigo) ou o nome do sistema.
    nome: str | None


class JobPublico(BaseModel):
    """O que a API mostra de um Job; o SHA-256 e o tamanho ficam no armazenamento."""

    id: str
    nome: str
    estado: Estado
    codigo_falha: CodigoDeFalha | None
    duracao_s: float | None
    # Cortes de câmera, em ms: os riscos da régua do Visualizador.
    cortes_ms: list[int] | None = None
    timecode_origem: str | None = None
    taxa_de_quadros: float | None = None
    programa: str | None = None
    data_exibicao: date | None = None
    indexacao: Indexacao | None = None
    enviado_por: EnviadoPor
    criado_em: datetime
    atualizado_em: datetime

    @classmethod
    def de(cls, job: Job) -> "JobPublico":
        campos = set(cls.model_fields) - {"enviado_por"}
        enviado_por = (
            EnviadoPor(tipo="sistema", nome=job.sistema)
            if job.sistema is not None
            else EnviadoPor(tipo="pessoa", nome=job.criado_por_email)
        )
        return cls(**job.model_dump(include=campos), enviado_por=enviado_por)


def _etag(publico: JobPublico) -> str:
    conteudo = publico.model_dump_json().encode()
    return f'"{hashlib.sha256(conteudo).hexdigest()[:32]}"'


def _casa_etag(if_none_match: str | None, etag: str) -> bool:
    """Comparação fraca do RFC 9110 §13.1.2: lista por vírgulas, `W/` ignorado, `*` casa."""
    if if_none_match is None:
        return False
    candidatos = [c.strip().removeprefix("W/") for c in if_none_match.split(",")]
    return "*" in candidatos or etag in candidatos


class JobCriado(JobPublico):
    url_de_upload: str


class Reproducao(BaseModel):
    url: str
    expira_em: datetime


class TipoNaoSuportado(Exception):
    """Corpo com tipo diferente de video/mp4: vira 415, antes de qualquer 422."""


class NovoJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    tamanho_bytes: Annotated[int, Field(strict=True)]
    tipo: Literal["video/mp4"]
    programa: str | None = None  # um nome de `programas.toml`
    data_exibicao: date | None = None

    @model_validator(mode="before")
    @classmethod
    def _tipo_antes_do_resto(cls, corpo: Any) -> Any:
        # Exceção fora de ValueError atravessa o Pydantic, e o 415 não vira 422
        # quando o nome ou o tamanho também estão errados (um .mov, por exemplo).
        if (
            isinstance(corpo, dict)
            and "tipo" in corpo
            and corpo["tipo"] != TIPO_DO_VIDEO
        ):
            raise TipoNaoSuportado
        return corpo

    @field_validator("nome")
    @classmethod
    def _nome_de_arquivo_mp4(cls, nome: str) -> str:
        if any(c in nome for c in "/\\") or any(ord(c) < 32 for c in nome):
            raise ValueError("nome com caminho ou caractere de controle")
        if not nome.lower().endswith(".mp4"):
            raise ValueError("nome sem extensão .mp4")
        return nome

    @field_validator("data_exibicao", mode="before")
    @classmethod
    def _data_so_como_texto(cls, valor: Any) -> Any:
        # O Pydantic leria um número como timestamp e aceitaria data com hora
        # zerada; aqui só vale "AAAA-MM-DD".
        if valor is not None and not (isinstance(valor, str) and len(valor) == 10):
            raise ValueError("data_exibicao deve ser texto AAAA-MM-DD")
        return valor

    @field_validator("programa")
    @classmethod
    def _programa_com_perfil(cls, programa: str | None) -> str | None:
        if programa is not None and programa not in PERFIS:
            raise ValueError("programa sem perfil")
        return programa


class ServicoIndisponivel(Exception):
    """Porta ainda sem adaptador real."""


class CursorInvalido(Exception):
    """O cursor não aponta para um Job que exista."""


Ordem = Literal["enviado", "exibicao"]
LIMITE_MAXIMO = 200


@dataclass(frozen=True)
class FiltroDeJobs:
    """Os filtros do acervo; todos opcionais e combináveis."""

    programa: str | None = None
    estados: frozenset[Estado] = frozenset()
    exibicao_de: date | None = None
    exibicao_ate: date | None = None
    palavras: tuple[str, ...] = ()  # já normalizadas: todas precisam estar no nome
    sistema: str | None = None
    ordem: Ordem = "enviado"
    limite: int | None = None  # `None`: a lista inteira, sem cursor
    cursor: str | None = None  # id do último Job da página anterior


@dataclass(frozen=True)
class PaginaDeJobs:
    jobs: list[Job]
    proximo_cursor: str | None = None

    @classmethod
    def de(cls, jobs: Iterable[Job], limite: int | None) -> "PaginaDeJobs":
        """Corta os Jobs já filtrados e em ordem; só lê um além do limite."""
        if limite is None:
            return cls(list(jobs))
        lidos = list(itertools.islice(jobs, limite + 1))
        if len(lidos) <= limite:
            return cls(lidos)
        pagina = lidos[:limite]
        return cls(pagina, pagina[-1].id)


def casa_com_o_filtro(job: Job, filtro: FiltroDeJobs) -> bool:
    """Todos os filtros menos ordem e paginação."""
    if filtro.programa is not None and job.programa != filtro.programa:
        return False
    if filtro.sistema is not None and job.sistema != filtro.sistema:
        return False
    if filtro.estados and job.estado not in filtro.estados:
        return False
    if filtro.exibicao_de is not None or filtro.exibicao_ate is not None:
        if job.data_exibicao is None:
            return False
        if filtro.exibicao_de and job.data_exibicao < filtro.exibicao_de:
            return False
        if filtro.exibicao_ate and job.data_exibicao > filtro.exibicao_ate:
            return False
    return all(p in job.palavras for p in filtro.palavras)


def chave_de_ordem(job: Job, ordem: Ordem) -> tuple[Any, ...]:
    """Maior primeiro. Na exibição, quem não tem data fica no fim; o id desempata."""
    if ordem == "exibicao":
        return (job.data_exibicao is not None, job.data_exibicao or date.min, job.id)
    return (job.criado_em, job.id)


class RepositorioDeJobs(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def salvar(self, job: Job) -> None: ...

    def obter(self, job_id: str) -> Job | None: ...

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        """Aplica `mudancas` só se o Job ainda estiver em `de`; atômica.

        Devolve o Job gravado, ou `None` se ele não existe ou já saiu de `de`.
        Quem decide as transições é `api.ciclo_de_vida`; use `transitar` de lá.
        """
        ...

    def listar(self) -> list[Job]:
        """Do mais recente para o mais antigo."""
        ...

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        """Filtra, ordena e pagina. Levanta `CursorInvalido` se o cursor não existe."""
        ...


class Armazenamento(Protocol):
    """Porta para o Cloud Storage; os testes usam uma versão falsa."""

    def url_de_upload(self, job_id: str, tamanho_bytes: int, tipo: str) -> str:
        """URL assinada para iniciar um upload retomável na quarentena, presa ao tipo e ao tamanho."""
        ...

    def cancelar_upload(self, job_id: str) -> None: ...

    def url_de_reproducao(self, job_id: str, validade: timedelta) -> str:
        """URL assinada de leitura do proxy de reprodução, válida por `validade`."""
        ...

    def url_do_quadro(self, job_id: str, caminho: str, validade: timedelta) -> str:
        """URL assinada de leitura do JPEG de `caminho` (o campo `quadro` da Decupagem)."""
        ...

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        """O JSON da decupagem, em pedaços."""
        ...


class RepositorioEmMemoria:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def salvar(self, job: Job) -> None:
        self._jobs[job.id] = job

    def obter(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None or job.estado != de:
            return None
        self._jobs[job_id] = job.model_copy(update=mudancas)
        return self._jobs[job_id]

    def listar(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.criado_em, reverse=True)

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        corte = None
        if filtro.cursor is not None:
            ancora = self._jobs.get(filtro.cursor)
            if ancora is None:
                raise CursorInvalido
            corte = chave_de_ordem(ancora, filtro.ordem)
        jobs = sorted(
            (
                j
                for j in self._jobs.values()
                if casa_com_o_filtro(j, filtro)
                and (corte is None or chave_de_ordem(j, filtro.ordem) < corte)
            ),
            key=lambda j: chave_de_ordem(j, filtro.ordem),
            reverse=True,
        )
        return PaginaDeJobs.de(jobs, filtro.limite)


class RepositorioIndisponivel:
    def salvar(self, job: Job) -> None:
        raise ServicoIndisponivel

    def obter(self, job_id: str) -> Job | None:
        raise ServicoIndisponivel

    def transitar(
        self, job_id: str, de: Estado, mudancas: dict[str, Any]
    ) -> Job | None:
        raise ServicoIndisponivel

    def listar(self) -> list[Job]:
        raise ServicoIndisponivel

    def consultar(self, filtro: FiltroDeJobs) -> PaginaDeJobs:
        raise ServicoIndisponivel


class ArmazenamentoIndisponivel:
    def url_de_upload(self, job_id: str, tamanho_bytes: int, tipo: str) -> str:
        raise ServicoIndisponivel

    def cancelar_upload(self, job_id: str) -> None:
        raise ServicoIndisponivel

    def url_de_reproducao(self, job_id: str, validade: timedelta) -> str:
        raise ServicoIndisponivel

    def url_do_quadro(self, job_id: str, caminho: str, validade: timedelta) -> str:
        raise ServicoIndisponivel

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        raise ServicoIndisponivel


def expirar_uploads(
    repositorio: RepositorioDeJobs, armazenamento: Armazenamento, agora: datetime
) -> list[str]:
    """Falha os Jobs sem upload completo há 24 h ou mais e cancela a sessão de upload."""
    expirados: list[str] = []
    for job in repositorio.listar():
        if job.estado != "aguardando_upload" or agora - job.criado_em < PRAZO_DO_UPLOAD:
            continue
        # Primeiro a transição: se o Job andou nesse meio-tempo, o upload é dele.
        if transitar(
            repositorio,
            job.id,
            "aguardando_upload",
            "falhou",
            agora,
            codigo_falha="upload_expirado",
        ):
            armazenamento.cancelar_upload(job.id)
            expirados.append(job.id)
    return expirados


def agora_utc() -> datetime:
    return datetime.now(UTC)


def _aceita_gzip(accept_encoding: str) -> bool:
    """`gzip` (ou `*`) no `Accept-Encoding`, sem `q=0`."""
    for opcao in accept_encoding.split(","):
        nome, *parametros = (parte.strip() for parte in opcao.split(";"))
        if nome.lower() not in ("gzip", "*"):
            continue
        for parametro in parametros:
            chave, _, valor = parametro.partition("=")
            if chave.strip().lower() == "q":
                try:
                    return float(valor) > 0
                except ValueError:
                    return False
        return True
    return False


def _comprimir(pedacos: Iterator[bytes]) -> Iterator[bytes]:
    compressor = zlib.compressobj(wbits=31)
    for pedaco in pedacos:
        if dados := compressor.compress(pedaco):
            yield dados
    yield compressor.flush()


# Permissão que a pessoa precisa para cada escopo de chave. Cancelar exige a de enviar.
PERMISSAO_DO_ESCOPO: dict[Escopo, Permissao] = {
    "criar": "video.enviar",
    "ler": "decupagem.ver",
    "cancelar": "video.enviar",
}


def _confere_permissao(request: Request, pessoa: Usuario, permissao: Permissao) -> None:
    """403 se a pessoa não tem a permissão por nenhum dos seus papéis."""
    if not _tem_permissao(request, pessoa, permissao):
        raise HTTPException(403, f"Sem a permissão {permissao}")


def _exige(escopo: Escopo) -> Callable[[Request, Chamador], Chamador]:
    """Dependência: chave sem o escopo, ou pessoa sem a permissão, recebe 403."""

    def verificar(request: Request, chamador: ChamadorAutenticado) -> Chamador:
        if isinstance(chamador, Sistema):
            if escopo not in chamador.escopos:
                raise HTTPException(403, f"Chave sem o escopo {escopo}")
            return chamador
        _confere_permissao(request, chamador, PERMISSAO_DO_ESCOPO[escopo])
        return chamador

    return verificar


def _exige_editar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `decupagem.editar`; chave de sistema não corrige."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não corrige a decupagem")
    _confere_permissao(request, chamador, "decupagem.editar")
    return chamador


def _exige_aprovar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `correcao.aprovar` (o Curador)."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não aprova correções")
    _confere_permissao(request, chamador, "correcao.aprovar")
    return chamador


def papeis_da_pessoa(request: Request, pessoa: Usuario) -> list[Papel]:
    """Os papéis efetivos, num ponto só para o `/v1/eu` e as rotas nunca discordarem."""
    papeis: RepositorioDePapeis = request.app.state.papeis
    return papeis_do_usuario(
        papeis.obter(pessoa.uid),
        pessoa.email,
        pessoa.email_verificado,
        request.app.state.admins,
    )


def _tem_permissao(request: Request, pessoa: Usuario, permissao: Permissao) -> bool:
    return permissao in permissoes_de(papeis_da_pessoa(request, pessoa))


def _enxerga(chamador: Chamador, job: Job | None) -> Job:
    """O job, ou 404 se não existe ou é de outro sistema (ou de uma pessoa), para uma chave."""
    if job is None or (
        isinstance(chamador, Sistema) and job.sistema != chamador.sistema
    ):
        raise HTTPException(404, "Job não encontrado")
    return job


def criar_rotas(
    repositorio: RepositorioDeJobs,
    armazenamento: Armazenamento,
    tamanho_maximo_bytes: int,
    relogio: Callable[[], datetime],
    correcoes: RepositorioDeCorrecoes,
    aprovacao: RepositorioDeAprovacao,
    catalogo: Catalogo,
    reindexar: Callable[[Job], object],
) -> APIRouter:
    rotas = APIRouter(prefix="/jobs")

    @rotas.post("", status_code=202)
    def criar(
        novo: NovoJob, chamador: Annotated[Chamador, Depends(_exige("criar"))]
    ) -> JobCriado:
        if not 0 < novo.tamanho_bytes <= tamanho_maximo_bytes:
            raise HTTPException(422, "Tamanho fora do limite")
        if isinstance(chamador, Sistema):
            criado_por, sistema = f"sistema:{chamador.sistema}", chamador.sistema
            email = None
        else:
            criado_por, sistema, email = chamador.uid, None, chamador.email or None
        agora = relogio()
        if (
            novo.data_exibicao is not None
            and novo.data_exibicao > agora.astimezone(FUSO_DA_EMISSORA).date()
        ):
            raise HTTPException(422, "Data de exibição no futuro")
        job = Job(
            id=uuid.uuid4().hex,
            nome=novo.nome,
            tamanho_bytes=novo.tamanho_bytes,
            estado="aguardando_upload",
            criado_por=criado_por,
            criado_por_email=email,
            sistema=sistema,
            palavras=palavras_do_nome(novo.nome),
            programa=novo.programa,
            data_exibicao=novo.data_exibicao,
            criado_em=agora,
            atualizado_em=agora,
        )
        repositorio.salvar(job)
        url = armazenamento.url_de_upload(job.id, job.tamanho_bytes, novo.tipo)
        return JobCriado(**JobPublico.de(job).model_dump(), url_de_upload=url)

    @rotas.get("", response_model=list[JobPublico])
    def listar(
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        programa: str | None = None,
        estado: Annotated[list[Estado] | None, Query()] = None,
        exibicao_de: date | None = None,
        exibicao_ate: date | None = None,
        q: str | None = None,
        sistema: str | None = None,
        ordem: Ordem = "enviado",
        limite: Annotated[int | None, Query(ge=1, le=LIMITE_MAXIMO)] = None,
        cursor: str | None = None,
    ) -> Response:
        if isinstance(chamador, Sistema):
            # Uma chave só vê os próprios Jobs; pedir os de outro sistema não acha nada.
            if sistema not in (None, chamador.sistema):
                return JSONResponse([])
            sistema = chamador.sistema
        filtro = FiltroDeJobs(
            programa=programa,
            estados=frozenset(estado or ()),
            exibicao_de=exibicao_de,
            exibicao_ate=exibicao_ate,
            palavras=tuple(palavras_do_nome(q or "")),
            sistema=sistema,
            ordem=ordem,
            limite=limite,
            cursor=cursor,
        )
        try:
            pagina = repositorio.consultar(filtro)
        except CursorInvalido:
            raise HTTPException(422, "Cursor inválido") from None
        corpo = [JobPublico.de(j).model_dump(mode="json") for j in pagina.jobs]
        cabecalhos = (
            {"X-Proximo-Cursor": pagina.proximo_cursor} if pagina.proximo_cursor else {}
        )
        return JSONResponse(corpo, headers=cabecalhos)

    @rotas.get("/{job_id}", response_model=JobPublico)
    def ler(
        job_id: str,
        request: Request,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
    ) -> Response:
        job = _enxerga(chamador, repositorio.obter(job_id))
        publico = JobPublico.de(job)
        etag = _etag(publico)
        cabecalhos = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if _casa_etag(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=cabecalhos)
        return JSONResponse(publico.model_dump(mode="json"), headers=cabecalhos)

    def obter_concluido(job_id: str, chamador: Chamador) -> Job:
        job = _enxerga(chamador, repositorio.obter(job_id))
        if job.estado != "concluido":
            raise HTTPException(409, f"Job em {job.estado}, não concluido")
        return job

    @rotas.delete("/{job_id}", status_code=202)
    def cancelar(
        job_id: str, chamador: Annotated[Chamador, Depends(_exige("cancelar"))]
    ) -> JobPublico:
        _enxerga(chamador, repositorio.obter(job_id))
        try:
            job = cancelar_job(repositorio, job_id, relogio())
        except JaTerminou as terminou:
            raise HTTPException(
                409, f"Job em {terminou.estado}, não cancelável"
            ) from None
        return JobPublico.de(_enxerga(chamador, job))

    @rotas.get("/{job_id}/reproducao")
    def reproducao(
        job_id: str, chamador: Annotated[Chamador, Depends(_exige("ler"))]
    ) -> Reproducao:
        job = obter_concluido(job_id, chamador)
        url = armazenamento.url_de_reproducao(job.id, VALIDADE_DA_REPRODUCAO)
        return Reproducao(url=url, expira_em=relogio() + VALIDADE_DA_REPRODUCAO)

    @rotas.get("/{job_id}/quadros/{arquivo}")
    def quadro(
        job_id: str,
        arquivo: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*\.jpg$")],
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
    ) -> Reproducao:
        job = obter_concluido(job_id, chamador)
        url = armazenamento.url_do_quadro(
            job.id, caminho_do_quadro(arquivo), VALIDADE_DA_REPRODUCAO
        )
        return Reproducao(url=url, expira_em=relogio() + VALIDADE_DA_REPRODUCAO)

    def _resposta(corpo: Iterator[bytes], request: Request) -> StreamingResponse:
        cabecalhos = {"Vary": "Accept-Encoding"}
        if _aceita_gzip(request.headers.get("accept-encoding", "")):
            cabecalhos["Content-Encoding"] = "gzip"
            corpo = _comprimir(corpo)
        return StreamingResponse(
            corpo, media_type="application/json", headers=cabecalhos
        )

    def _ler_modelo(job_id: str) -> tuple[dict[str, Any], str]:
        """O JSON do modelo e a versão (SHA-256 dos bytes guardados)."""
        conteudo = b"".join(armazenamento.abrir_decupagem(job_id))
        return json.loads(conteudo), versao_do_modelo(conteudo)

    def _ler_correcoes(job_id: str) -> list[Correcao]:
        return correcoes.listar(job_id)

    @rotas.get("/{job_id}/decupagem")
    def decupagem(
        job_id: str,
        request: Request,
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
        versao: Literal["modelo"] | None = None,
    ) -> StreamingResponse:
        job = obter_concluido(job_id, chamador)
        if versao == "modelo":
            pedacos = iter(armazenamento.abrir_decupagem(job.id))
            # Lê o primeiro pedaço antes do 200: uma falha ao abrir vira 503, não um JSON cortado.
            pedacos = itertools.chain([next(pedacos, b"")], pedacos)
            return _resposta(pedacos, request)
        modelo, versao_atual = _ler_modelo(job.id)
        entregue = decupagem_entregue(modelo, versao_atual, _ler_correcoes(job.id))
        return _resposta(iter([json.dumps(entregue).encode()]), request)

    def _espera_curador(request: Request, autor: Usuario, tipo: str) -> bool:
        """Só a correção de quem não é Curador, num tipo da lista, espera decisão."""
        return tipo in aprovacao.tipos() and not _tem_permissao(
            request, autor, "correcao.aprovar"
        )

    def _autoria(autor: Usuario) -> Autoria:
        return Autoria(autor.uid, autor.email, relogio())

    @rotas.post("/{job_id}/correcoes", status_code=201)
    def corrigir_decupagem(
        job_id: str,
        request: Request,
        novo: NovaCorrecao,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        job = obter_concluido(job_id, autor)
        modelo, versao_atual = _ler_modelo(job.id)
        try:
            correcao = corrigir(
                modelo,
                versao_atual,
                _ler_correcoes(job.id),
                novo,
                job.id,
                _autoria(autor),
                exige_aprovacao=_espera_curador(request, autor, novo.tipo),
                catalogo=catalogo,
            )
        except VersaoDesatualizada:
            raise HTTPException(
                409, "A decupagem mudou: recarregue e corrija de novo"
            ) from None
        except ItemInexistente:
            raise HTTPException(422, "Item inexistente") from None
        except TemposInvalidos:
            raise HTTPException(422, "Tempos além da duração do vídeo") from None
        correcoes.acrescentar(correcao)
        # Pendente não vale ainda: o índice só muda quando o Curador aprovar.
        if not correcao.exige_aprovacao:
            reindexar(job)
        return {"id": correcao.id, "versao_decupagem": versao_atual}

    @rotas.get("/{job_id}/correcoes")
    def historico_de_correcoes(
        job_id: str, autor: Annotated[Usuario, Depends(_exige_editar)]
    ) -> list[ItemDoHistorico]:
        job = obter_concluido(job_id, autor)
        return historico(_ler_correcoes(job.id))

    @rotas.post("/{job_id}/correcoes/{correcao_id}/desfazer", status_code=201)
    def desfazer_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovoDesfazer,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        job = obter_concluido(job_id, autor)
        modelo, versao_atual = _ler_modelo(job.id)
        try:
            registro = desfazer(
                modelo,
                versao_atual,
                _ler_correcoes(job.id),
                correcao_id,
                corpo.motivo,
                job.id,
                _autoria(autor),
            )
            correcoes.acrescentar(registro)
        except CorrecaoInexistente:
            raise HTTPException(404, "Correção não encontrada") from None
        except (NaoDesfazivel, CorrecaoJaExiste):
            raise HTTPException(
                409,
                "Correção já desfeita, saiu da fila, não é uma renomeação"
                " ou não casa com a versão atual",
            ) from None
        reindexar(job)
        return {"id": registro.id}

    @rotas.get("/{job_id}/fila")
    def fila_de_revisao(
        job_id: str, autor: Annotated[Usuario, Depends(_exige_editar)]
    ) -> list[ItemDaFila]:
        job = obter_concluido(job_id, autor)
        modelo, versao_atual = _ler_modelo(job.id)
        return fila(modelo, versao_atual, _ler_correcoes(job.id))

    def _tirar_da_fila(
        job_id: str,
        autor: Usuario,
        resolver: Callable[
            [dict[str, Any], str, list[Correcao], str, Autoria], Correcao
        ],
    ) -> dict[str, str]:
        """`resolver` é `reaplicar` ou `descartar` já com o pedido da rota; recebe
        o modelo, a versão, as Correções, o Job e a autoria."""
        job = obter_concluido(job_id, autor)
        modelo, versao_atual = _ler_modelo(job.id)
        try:
            registro = resolver(
                modelo, versao_atual, _ler_correcoes(job.id), job.id, _autoria(autor)
            )
            correcoes.acrescentar(registro)
        except CorrecaoInexistente:
            raise HTTPException(404, "Correção não encontrada") from None
        except NaoCandidato:
            raise HTTPException(422, "O item não é candidato desta correção") from None
        except TemposInvalidos:
            raise HTTPException(422, "Tempos além da duração do vídeo") from None
        except (NaoNaFila, CorrecaoJaExiste):
            raise HTTPException(409, "A correção não está mais na fila") from None
        reindexar(job)
        return {"id": registro.id}

    @rotas.post("/{job_id}/fila/{correcao_id}/reaplicar", status_code=201)
    def reaplicar_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovaReaplicacao,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        # Não espera o Curador: só reaponta uma correção que já valia (pendente
        # não vai para a fila), e a original sai da fila quando ela nasce.
        return _tirar_da_fila(
            job_id,
            autor,
            lambda modelo, versao, todas, job, autoria: reaplicar(
                modelo,
                versao,
                todas,
                correcao_id,
                corpo.item_id,
                corpo.motivo,
                job,
                autoria,
            ),
        )

    @rotas.post("/{job_id}/fila/{correcao_id}/descartar", status_code=201)
    def descartar_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovaResolucao,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        return _tirar_da_fila(
            job_id,
            autor,
            lambda modelo, versao, todas, job, autoria: descartar(
                modelo, versao, todas, correcao_id, corpo.motivo, job, autoria
            ),
        )

    def _decidir(
        job_id: str,
        correcao_id: str,
        autor: Usuario,
        aprovada: bool,
        motivo: str = "",
    ) -> dict[str, str]:
        job = obter_concluido(job_id, autor)
        try:
            registro = decidir(
                _ler_correcoes(job.id),
                correcao_id,
                aprovada,
                motivo,
                job.id,
                _autoria(autor),
            )
            correcoes.acrescentar(registro)
        except CorrecaoInexistente:
            raise HTTPException(404, "Correção não encontrada") from None
        except (NaoPendente, CorrecaoJaExiste):
            raise HTTPException(409, "A correção não está pendente") from None
        if aprovada:
            reindexar(job)
        return {"id": registro.id}

    @rotas.post("/{job_id}/correcoes/{correcao_id}/aprovar", status_code=201)
    def aprovar_correcao(
        job_id: str,
        correcao_id: str,
        autor: Annotated[Usuario, Depends(_exige_aprovar)],
    ) -> dict[str, str]:
        return _decidir(job_id, correcao_id, autor, True)

    @rotas.post("/{job_id}/correcoes/{correcao_id}/recusar", status_code=201)
    def recusar_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovaRecusa,
        autor: Annotated[Usuario, Depends(_exige_aprovar)],
    ) -> dict[str, str]:
        return _decidir(job_id, correcao_id, autor, False, corpo.motivo)

    return rotas
