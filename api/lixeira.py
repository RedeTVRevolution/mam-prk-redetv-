"""Lixeira dos vídeos (E8): mandar para a lixeira e restaurar, em `/v1/admin/lixeira`.

A lixeira não apaga nada: o Job só ganha `lixeira` (quando, quem, por quê) e some para quem
não é Administrador. Quem apaga de fato é a purga, depois de 30 dias (ADR 0010).
"""

import math
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StringConstraints

from api.auditoria import Acao, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.catalogo import Catalogo, EnvioParaLixeira
from api.correcoes import RepositorioDeCorrecoes
from api.jobs import (
    FiltroDeJobs,
    Job,
    RepositorioDeJobs,
    _confere_permissao,
    _tem_permissao,
)
from api.marcas import CatalogoDeMarcas

PRAZO_DA_PURGA = timedelta(days=30)
MOTIVO_MAXIMO = 500
# Em andamento, o Job ainda escreve nos arquivos: cancelar primeiro.
ESTADOS_QUE_VAO_PARA_A_LIXEIRA = ("concluido", "falhou", "cancelado")


class ArquivosContados(BaseModel):
    decupagem: int = 0
    copia_limpa: int = 0
    proxy: int = 0
    quadros: int = 0


class ArquivosDoJob(Protocol):
    """Porta para o Storage: quantos arquivos o Job tem; os testes usam a versão em memória."""

    def contar(self, job_id: str) -> ArquivosContados: ...

    def apagar(self, job_id: str) -> None:
        """Apaga tudo o que o Job tem nos buckets. Só a purga (`api.purga`) chama."""
        ...


class ArquivosEmMemoria:
    def __init__(self) -> None:
        self.por_job: dict[str, ArquivosContados] = {}

    def contar(self, job_id: str) -> ArquivosContados:
        return self.por_job.get(job_id, ArquivosContados())

    def apagar(self, job_id: str) -> None:
        self.por_job.pop(job_id, None)


class ArquivosDoImpacto(BaseModel):
    copia_limpa: int
    proxy: int
    quadros: int


class OutroJob(BaseModel):
    id: str
    nome: str
    enviado_por: str


class ImpactoDoVideo(BaseModel):
    """O que vai junto com o vídeo; a tela mostra antes de confirmar."""

    decupagem: int
    correcoes: int
    arquivos: ArquivosDoImpacto
    # Outros Jobs com o mesmo conteúdo: a decupagem continua para eles.
    outros_jobs: list[OutroJob]


class ItemDaLixeira(BaseModel):
    tipo: Literal["video", "pessoa", "marca"]
    id: str
    nome: str
    enviado_por: str
    enviado_em: datetime
    motivo: str
    dias_ate_a_purga: int


class Envio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    motivo: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MOTIVO_MAXIMO
        ),
    ]


def sem_job_na_lixeira(
    repositorio: RepositorioDeJobs,
) -> Callable[[Request, ChamadorAutenticado], None]:
    """Dependência de `/v1`: toda rota com `{job_id}` dá 404 ao Job na lixeira, menos ao
    Administrador, que o lê para conferir e restaurar."""

    def verificar(request: Request, chamador: ChamadorAutenticado) -> None:
        job_id = request.path_params.get("job_id")
        if job_id is None:
            return
        job = repositorio.obter(job_id)
        if job is None or job.lixeira is None:
            return
        if isinstance(chamador, Usuario) and _tem_permissao(
            request, chamador, "lixeira.gerir"
        ):
            return
        raise HTTPException(404, "Job não encontrado")

    return verificar


def _exige_gerir(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `lixeira.gerir`; chave de sistema não mexe na lixeira."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não mexe na lixeira")
    _confere_permissao(request, chamador, "lixeira.gerir")
    return chamador


def _quem_enviou(job: Job) -> str:
    return job.sistema or job.criado_por_email or job.criado_por


class JobRestaurado(BaseModel):
    id: str
    nome: str


def item_da_lixeira(
    tipo: Literal["video", "pessoa", "marca"],
    id: str,
    nome: str,
    envio: EnvioParaLixeira,
    agora: datetime,
) -> ItemDaLixeira:
    faltam = envio.em + PRAZO_DA_PURGA - agora
    return ItemDaLixeira(
        tipo=tipo,
        id=id,
        nome=nome,
        enviado_por=envio.por_email,
        enviado_em=envio.em,
        motivo=envio.motivo,
        dias_ate_a_purga=max(0, math.ceil(faltam / timedelta(days=1))),
    )


def _item(job: Job, envio: EnvioParaLixeira, agora: datetime) -> ItemDaLixeira:
    return item_da_lixeira("video", job.id, job.nome, envio, agora)


def login_recente_ou_403(pessoa: Usuario, agora: datetime, janela: timedelta) -> None:
    """A purga manual pede um login com MFA recente (`auth_time` do token)."""
    if pessoa.login_em is None or agora - pessoa.login_em > janela:
        raise HTTPException(403, "login_recente_exigido")


def calcular_impacto(
    job: Job,
    repositorio: RepositorioDeJobs,
    correcoes: RepositorioDeCorrecoes,
    arquivos: ArquivosDoJob,
) -> ImpactoDoVideo:
    contados = arquivos.contar(job.id)
    # Os que estão na lixeira também contam: podem ser restaurados e ainda usam o
    # processamento.
    parecidos = (
        repositorio.consultar(FiltroDeJobs(sha256=job.sha256, na_lixeira=None)).jobs
        if job.sha256 is not None
        else []
    )
    return ImpactoDoVideo(
        decupagem=contados.decupagem,
        correcoes=len(correcoes.listar(job.id)),
        arquivos=ArquivosDoImpacto(
            copia_limpa=contados.copia_limpa,
            proxy=contados.proxy,
            quadros=contados.quadros,
        ),
        outros_jobs=[
            OutroJob(id=j.id, nome=j.nome, enviado_por=_quem_enviou(j))
            for j in parecidos
            if j.id != job.id and j.sha256 == job.sha256
        ],
    )


def criar_rotas_da_lixeira(
    repositorio: RepositorioDeJobs,
    correcoes: RepositorioDeCorrecoes,
    arquivos: ArquivosDoJob,
    auditoria: RepositorioDeAuditoria,
    relogio: Callable[[], datetime],
    pessoas: Catalogo,
    marcas: CatalogoDeMarcas,
) -> APIRouter:
    # O parâmetro não se chama `job_id`: a dependência `sem_job_na_lixeira` esconderia
    # da própria lixeira o Job que ela precisa mostrar.
    rotas = APIRouter(prefix="/admin/lixeira")

    def achar(id_do_video: str) -> Job:
        job = repositorio.obter(id_do_video)
        if job is None:
            raise HTTPException(404, "Job não encontrado")
        return job

    def impacto_de(job: Job) -> ImpactoDoVideo:
        return calcular_impacto(job, repositorio, correcoes, arquivos)

    def registrar(
        autor: Usuario,
        acao: Acao,
        job: Job,
        motivo: str,
        impacto: ImpactoDoVideo,
    ) -> None:
        auditoria.acrescentar(
            RegistroDeAuditoria(
                id=uuid.uuid4().hex,
                quando=relogio(),
                uid=autor.uid,
                email=autor.email,
                acao=acao,
                alvo_tipo="video",
                alvo_id=job.id,
                alvo_nome=job.nome,
                motivo=motivo,
                detalhes=impacto.model_dump(mode="json"),
            )
        )

    @rotas.get("")
    def listar(
        _pessoa: Annotated[Usuario, Depends(_exige_gerir)],
    ) -> list[ItemDaLixeira]:
        agora = relogio()
        itens = [
            _item(job, job.lixeira, agora)
            for job in repositorio.consultar(FiltroDeJobs(na_lixeira=True)).jobs
            if job.lixeira is not None
        ]
        itens += [
            item_da_lixeira("pessoa", p.id, p.nome, p.lixeira, agora)
            for p in pessoas.na_lixeira()
            if p.lixeira is not None
        ]
        itens += [
            item_da_lixeira("marca", m.id, m.nome, m.lixeira, agora)
            for m in marcas.na_lixeira()
            if m.lixeira is not None
        ]
        return sorted(itens, key=lambda i: i.enviado_em, reverse=True)

    @rotas.get("/videos/{id_do_video}/impacto")
    def impacto(
        id_do_video: str, _pessoa: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> ImpactoDoVideo:
        return impacto_de(achar(id_do_video))

    @rotas.post("/videos/{id_do_video}", status_code=201)
    def enviar(
        id_do_video: str,
        pedido: Envio,
        pessoa: Annotated[Usuario, Depends(_exige_gerir)],
    ) -> ItemDaLixeira:
        job = achar(id_do_video)
        if job.estado not in ESTADOS_QUE_VAO_PARA_A_LIXEIRA:
            raise HTTPException(
                409, f"Job em {job.estado}: cancele antes de mandar para a lixeira"
            )
        if job.lixeira is not None:
            raise HTTPException(409, "O vídeo já está na lixeira")
        impacto = impacto_de(job)
        envio = EnvioParaLixeira(
            em=relogio(),
            por_uid=pessoa.uid,
            por_email=pessoa.email.lower(),
            motivo=pedido.motivo,
        )

        def mudar(atual: Job) -> dict[str, object] | None:
            if (
                atual.estado not in ESTADOS_QUE_VAO_PARA_A_LIXEIRA
                or atual.lixeira is not None
            ):
                return None
            return {"lixeira": envio}

        if repositorio.trocar(job.id, mudar) is None:
            raise HTTPException(409, "O vídeo mudou de estado: tente de novo")
        try:
            registrar(pessoa, "item.para_lixeira", job, pedido.motivo, impacto)
        except Exception:
            # Sem registro, o vídeo volta: o histórico de apagamentos não pode ter buraco.
            repositorio.trocar(job.id, lambda _: {"lixeira": None})
            raise
        return _item(job, envio, relogio())

    @rotas.post("/videos/{id_do_video}/restaurar")
    def restaurar(
        id_do_video: str, pessoa: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> JobRestaurado:
        job = achar(id_do_video)
        envio = job.lixeira
        if envio is None:
            raise HTTPException(409, "O vídeo não está na lixeira")
        impacto = impacto_de(job)
        if (
            repositorio.trocar(
                job.id, lambda atual: {"lixeira": None} if atual.lixeira else None
            )
            is None
        ):
            raise HTTPException(409, "O vídeo não está na lixeira")
        try:
            registrar(pessoa, "item.restaurado", job, envio.motivo, impacto)
        except Exception:
            repositorio.trocar(job.id, lambda _: {"lixeira": envio})
            raise
        return JobRestaurado(id=job.id, nome=job.nome)

    return rotas
