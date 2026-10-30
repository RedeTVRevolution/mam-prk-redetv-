"""Jobs da E0: modelo, portas (Firestore e Storage) e rotas `/v1/jobs`."""

import hashlib
import itertools
import json
import uuid
import zlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
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
from api.correcoes import (
    Correcao,
    CorrecaoJaExiste,
    ItemDaFila,
    ItemDoHistorico,
    ItemInexistente,
    NaoCandidato,
    NaoDesfazivel,
    NaoNaFila,
    NovaCorrecao,
    NovaReaplicacao,
    NovaResolucao,
    NovoDesfazer,
    RepositorioDeCorrecoes,
    TemposInvalidos,
    aplicar,
    fila,
    historico,
    id_da_resolucao,
    id_do_desfazer,
    montar_correcao,
    montar_descarte,
    montar_desfazer,
    montar_reaplicacao,
    valor_atual,
    versao_do_modelo,
)
from api.papeis import Permissao, RepositorioDePapeis, papeis_efetivos, permissoes_de

TIPO_DO_VIDEO = "video/mp4"
TAMANHO_MAXIMO_PADRAO_BYTES = 4 * 1024**3
PRAZO_DO_UPLOAD = timedelta(hours=24)
VALIDADE_DA_REPRODUCAO = timedelta(minutes=10)

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
    sistema: str | None = None
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

    def listar_por_sistema(self, sistema: str) -> list[Job]:
        """Só os jobs do sistema, do mais recente para o mais antigo."""
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

    def listar_por_sistema(self, sistema: str) -> list[Job]:
        return [j for j in self.listar() if j.sistema == sistema]


class RepositorioIndisponivel:
    def salvar(self, job: Job) -> None:
        raise ServicoIndisponivel

    def obter(self, job_id: str) -> Job | None:
        raise ServicoIndisponivel

    def listar(self) -> list[Job]:
        raise ServicoIndisponivel

    def listar_por_sistema(self, sistema: str) -> list[Job]:
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


def _confere_permissao(request: Request, uid: str, permissao: Permissao) -> None:
    """403 se a pessoa não tem a permissão por nenhum dos seus papéis."""
    papeis: RepositorioDePapeis = request.app.state.papeis
    if permissao not in permissoes_de(papeis_efetivos(papeis.obter(uid))):
        raise HTTPException(403, f"Sem a permissão {permissao}")


def _exige(escopo: Escopo) -> Callable[[Request, Chamador], Chamador]:
    """Dependência: chave sem o escopo, ou pessoa sem a permissão, recebe 403."""

    def verificar(request: Request, chamador: ChamadorAutenticado) -> Chamador:
        if isinstance(chamador, Sistema):
            if escopo not in chamador.escopos:
                raise HTTPException(403, f"Chave sem o escopo {escopo}")
            return chamador
        _confere_permissao(request, chamador.uid, PERMISSAO_DO_ESCOPO[escopo])
        return chamador

    return verificar


def _exige_editar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `decupagem.editar`; chave de sistema não corrige."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não corrige a decupagem")
    _confere_permissao(request, chamador.uid, "decupagem.editar")
    return chamador


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
        else:
            criado_por, sistema = chamador.uid, None
        agora = relogio()
        job = Job(
            id=uuid.uuid4().hex,
            nome=novo.nome,
            tamanho_bytes=novo.tamanho_bytes,
            estado="aguardando_upload",
            criado_por=criado_por,
            sistema=sistema,
            criado_em=agora,
            atualizado_em=agora,
        )
        repositorio.salvar(job)
        url = armazenamento.url_de_upload(job.id, job.tamanho_bytes, novo.tipo)
        return JobCriado(**JobPublico.de(job).model_dump(), url_de_upload=url)

    @rotas.get("")
    def listar(
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
    ) -> list[JobPublico]:
        if isinstance(chamador, Sistema):
            jobs = repositorio.listar_por_sistema(chamador.sistema)
        else:
            jobs = repositorio.listar()
        return [JobPublico.de(j) for j in jobs]

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
        job = _enxerga(chamador, repositorio.obter(job_id))
        if job.estado in ("concluido", "falhou"):
            raise HTTPException(409, f"Job em {job.estado}, não cancelável")
        if job.estado != "cancelado":
            job = job.model_copy(
                update={"estado": "cancelado", "atualizado_em": relogio()}
            )
            repositorio.salvar(job)
        return JobPublico.de(job)

    @rotas.get("/{job_id}/reproducao")
    def reproducao(
        job_id: str, chamador: Annotated[Chamador, Depends(_exige("ler"))]
    ) -> Reproducao:
        job = obter_concluido(job_id, chamador)
        url = armazenamento.url_de_reproducao(job.id, VALIDADE_DA_REPRODUCAO)
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
        entregue = aplicar(modelo, versao_atual, correcoes.listar(job.id))
        entregue["versao_decupagem"] = versao_atual
        return _resposta(iter([json.dumps(entregue).encode()]), request)

    @rotas.post("/{job_id}/correcoes", status_code=201)
    def corrigir(
        job_id: str,
        novo: NovaCorrecao,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        job = obter_concluido(job_id, autor)
        modelo, versao_atual = _ler_modelo(job.id)
        if novo.versao != versao_atual:
            raise HTTPException(409, "A decupagem mudou: recarregue e corrija de novo")
        try:
            antes = valor_atual(
                modelo, versao_atual, correcoes.listar(job.id), novo.tipo, novo.item_id
            )
            correcao = montar_correcao(
                modelo,
                versao_atual,
                novo,
                antes,
                id=uuid.uuid4().hex,
                job_id=job.id,
                autor_uid=autor.uid,
                autor_email=autor.email,
                criada_em=relogio(),
            )
        except ItemInexistente:
            raise HTTPException(422, "Item inexistente") from None
        except TemposInvalidos:
            raise HTTPException(422, "Tempos além da duração do vídeo") from None
        correcoes.acrescentar(correcao)
        return {"id": correcao.id, "versao_decupagem": versao_atual}

    @rotas.get("/{job_id}/correcoes")
    def historico_de_correcoes(
        job_id: str, autor: Annotated[Usuario, Depends(_exige_editar)]
    ) -> list[ItemDoHistorico]:
        job = obter_concluido(job_id, autor)
        return historico(correcoes.listar(job.id))

    @rotas.post("/{job_id}/correcoes/{correcao_id}/desfazer", status_code=201)
    def desfazer_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovoDesfazer,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        job = obter_concluido(job_id, autor)
        todas = correcoes.listar(job.id)
        alvo = next((c for c in todas if c.id == correcao_id), None)
        if alvo is None:
            raise HTTPException(404, "Correção não encontrada")
        modelo, versao_atual = _ler_modelo(job.id)
        try:
            desfazer = montar_desfazer(
                modelo,
                versao_atual,
                alvo,
                todas,
                corpo.motivo,
                id=id_do_desfazer(alvo.id),
                job_id=job.id,
                autor_uid=autor.uid,
                autor_email=autor.email,
                criada_em=relogio(),
            )
            correcoes.acrescentar(desfazer)
        except (NaoDesfazivel, CorrecaoJaExiste):
            raise HTTPException(
                409,
                "Correção já desfeita, saiu da fila, não é uma renomeação"
                " ou não casa com a versão atual",
            ) from None
        return {"id": desfazer.id}

    @rotas.get("/{job_id}/fila")
    def fila_de_revisao(
        job_id: str, autor: Annotated[Usuario, Depends(_exige_editar)]
    ) -> list[ItemDaFila]:
        job = obter_concluido(job_id, autor)
        modelo, versao_atual = _ler_modelo(job.id)
        return fila(modelo, versao_atual, correcoes.listar(job.id))

    def _resolver(
        job_id: str,
        correcao_id: str,
        autor: Usuario,
        montar: Callable[..., Correcao],
    ) -> dict[str, str]:
        """`montar(modelo, versao, alvo, todas, **registro)` faz o registro que
        tira a correção da fila (reaplicação ou descarte)."""
        job = obter_concluido(job_id, autor)
        todas = correcoes.listar(job.id)
        alvo = next((c for c in todas if c.id == correcao_id), None)
        if alvo is None:
            raise HTTPException(404, "Correção não encontrada")
        modelo, versao_atual = _ler_modelo(job.id)
        try:
            resolucao = montar(
                modelo,
                versao_atual,
                alvo,
                todas,
                id=id_da_resolucao(alvo.id),
                job_id=job.id,
                autor_uid=autor.uid,
                autor_email=autor.email,
                criada_em=relogio(),
            )
            correcoes.acrescentar(resolucao)
        except NaoCandidato:
            raise HTTPException(422, "O item não é candidato desta correção") from None
        except (NaoNaFila, CorrecaoJaExiste):
            raise HTTPException(409, "A correção não está mais na fila") from None
        return {"id": resolucao.id}

    @rotas.post("/{job_id}/fila/{correcao_id}/reaplicar", status_code=201)
    def reaplicar_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovaReaplicacao,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        return _resolver(
            job_id,
            correcao_id,
            autor,
            lambda modelo, versao, alvo, todas, **registro: montar_reaplicacao(
                modelo, versao, alvo, todas, corpo.item_id, corpo.motivo, **registro
            ),
        )

    @rotas.post("/{job_id}/fila/{correcao_id}/descartar", status_code=201)
    def descartar_correcao(
        job_id: str,
        correcao_id: str,
        corpo: NovaResolucao,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> dict[str, str]:
        return _resolver(
            job_id,
            correcao_id,
            autor,
            lambda modelo, versao, alvo, todas, **registro: montar_descarte(
                modelo, versao, alvo, todas, corpo.motivo, **registro
            ),
        )

    return rotas
