"""Jobs da E0: modelo, portas (Firestore e Storage) e rotas `/v1/jobs`."""

import uuid
import zlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from api.auth import UsuarioAutenticado

TIPO_DO_VIDEO = "video/mp4"
TAMANHO_MAXIMO_PADRAO_BYTES = 4 * 1024**3
PRAZO_DO_UPLOAD = timedelta(hours=24)
VALIDADE_DA_REPRODUCAO = timedelta(minutes=10)

Estado = Literal["aguardando_upload", "validando", "analisando", "concluido", "falhou"]
CodigoDeFalha = Literal[
    "formato_invalido",
    "arquivo_corrompido",
    "codec_nao_suportado",
    "duracao_excedida",
    "upload_expirado",
    "analise_falhou",
]


class Job(BaseModel):
    id: str
    nome: str
    tamanho_bytes: int
    sha256: str | None = None
    duracao_s: float | None = None
    estado: Estado
    codigo_falha: CodigoDeFalha | None = None
    criado_por: str
    criado_em: datetime
    atualizado_em: datetime


class JobPublico(BaseModel):
    """O que a API mostra de um Job; o SHA-256 e o tamanho ficam no armazenamento."""

    id: str
    nome: str
    estado: Estado
    codigo_falha: CodigoDeFalha | None
    duracao_s: float | None
    criado_em: datetime
    atualizado_em: datetime

    @classmethod
    def de(cls, job: Job) -> "JobPublico":
        return cls(**job.model_dump(include=set(cls.model_fields)))


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


class ServicoIndisponivel(Exception):
    """Porta ainda sem adaptador real."""


class RepositorioDeJobs(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def salvar(self, job: Job) -> None: ...

    def obter(self, job_id: str) -> Job | None: ...

    def listar(self) -> list[Job]:
        """Do mais recente para o mais antigo."""
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

    def listar(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.criado_em, reverse=True)


class RepositorioIndisponivel:
    def salvar(self, job: Job) -> None:
        raise ServicoIndisponivel

    def obter(self, job_id: str) -> Job | None:
        raise ServicoIndisponivel

    def listar(self) -> list[Job]:
        raise ServicoIndisponivel


class ArmazenamentoIndisponivel:
    def url_de_upload(self, job_id: str, tamanho_bytes: int, tipo: str) -> str:
        raise ServicoIndisponivel

    def cancelar_upload(self, job_id: str) -> None:
        raise ServicoIndisponivel

    def url_de_reproducao(self, job_id: str, validade: timedelta) -> str:
        raise ServicoIndisponivel

    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]:
        raise ServicoIndisponivel


def expirar_uploads(
    repositorio: RepositorioDeJobs, armazenamento: Armazenamento, agora: datetime
) -> list[str]:
    """Falha os Jobs sem upload completo há 24 h ou mais e cancela a sessão de upload."""
    expirados: list[str] = []
    for job in repositorio.listar():
        if (
            job.estado == "aguardando_upload"
            and agora - job.criado_em >= PRAZO_DO_UPLOAD
        ):
            armazenamento.cancelar_upload(job.id)
            repositorio.salvar(
                job.model_copy(
                    update={
                        "estado": "falhou",
                        "codigo_falha": "upload_expirado",
                        "atualizado_em": agora,
                    }
                )
            )
            expirados.append(job.id)
    return expirados


def agora_utc() -> datetime:
    return datetime.now(UTC)


def _comprimir(pedacos: Iterator[bytes]) -> Iterator[bytes]:
    compressor = zlib.compressobj(wbits=31)
    for pedaco in pedacos:
        if dados := compressor.compress(pedaco):
            yield dados
    yield compressor.flush()


def criar_rotas(
    repositorio: RepositorioDeJobs,
    armazenamento: Armazenamento,
    tamanho_maximo_bytes: int,
    relogio: Callable[[], datetime],
) -> APIRouter:
    rotas = APIRouter(prefix="/jobs")

    @rotas.post("", status_code=202)
    def criar(novo: NovoJob, usuario: UsuarioAutenticado) -> JobCriado:
        if not 0 < novo.tamanho_bytes <= tamanho_maximo_bytes:
            raise HTTPException(422, "Tamanho fora do limite")
        agora = relogio()
        job = Job(
            id=uuid.uuid4().hex,
            nome=novo.nome,
            tamanho_bytes=novo.tamanho_bytes,
            estado="aguardando_upload",
            criado_por=usuario.uid,
            criado_em=agora,
            atualizado_em=agora,
        )
        repositorio.salvar(job)
        url = armazenamento.url_de_upload(job.id, job.tamanho_bytes, novo.tipo)
        return JobCriado(**JobPublico.de(job).model_dump(), url_de_upload=url)

    @rotas.get("")
    def listar() -> list[JobPublico]:
        return [JobPublico.de(j) for j in repositorio.listar()]

    @rotas.get("/{job_id}")
    def ler(job_id: str) -> JobPublico:
        job = repositorio.obter(job_id)
        if job is None:
            raise HTTPException(404, "Job não encontrado")
        return JobPublico.de(job)

    def concluido(job_id: str) -> Job:
        job = repositorio.obter(job_id)
        if job is None:
            raise HTTPException(404, "Job não encontrado")
        if job.estado != "concluido":
            raise HTTPException(409, "Job ainda não concluído")
        return job

    @rotas.get("/{job_id}/reproducao")
    def reproducao(job_id: str) -> Reproducao:
        job = concluido(job_id)
        url = armazenamento.url_de_reproducao(job.id, VALIDADE_DA_REPRODUCAO)
        return Reproducao(url=url, expira_em=relogio() + VALIDADE_DA_REPRODUCAO)

    @rotas.get("/{job_id}/decupagem")
    def decupagem(job_id: str, request: Request) -> StreamingResponse:
        job = concluido(job_id)
        pedacos = armazenamento.abrir_decupagem(job.id)
        cabecalhos = {"Vary": "Accept-Encoding"}
        if "gzip" in request.headers.get("accept-encoding", ""):
            cabecalhos["Content-Encoding"] = "gzip"
            pedacos = _comprimir(pedacos)
        return StreamingResponse(
            pedacos, media_type="application/json", headers=cabecalhos
        )

    return rotas
