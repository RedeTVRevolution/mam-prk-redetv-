"""Purga dos vídeos na lixeira (E8): a única coisa que apaga de verdade (ADR 0010).

A manual vem de `POST /v1/admin/lixeira/videos/{id}/purgar`, só do Administrador, com o
nome do arquivo digitado e um login com MFA recente. A automática é o Cloud Run Job
`python -m api.purga`, que o Cloud Scheduler dispara uma vez por dia e que purga o que está
na lixeira há 30 dias ou mais.
"""

import logging
import os
import sys
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel, ConfigDict

from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.auditoria import RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import Usuario
from api.comparar_objetos import FaltaNoAmbiente, exigir_do_ambiente
from api.correcoes import RepositorioDeCorrecoes
from api.indice_da_busca import IndiceDaBusca
from api.jobs import FiltroDeJobs, Job, RepositorioDeJobs, agora_utc
from api.lixeira import (
    PRAZO_DA_PURGA,
    ArquivosDoImpacto,
    ArquivosDoJob,
    ImpactoDoVideo,
    _exige_gerir,
    calcular_impacto,
)
from api.nuvem import (
    ArquivosNoStorage,
    RepositorioDeAuditoriaFirestore,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
)

log = logging.getLogger(__name__)

SISTEMA_DA_PURGA = "Purga automática"
LOGIN_RECENTE_PADRAO = timedelta(minutes=5)


class NaoEstaNaLixeira(Exception):
    """O vídeo não existe, ou já saiu da lixeira (restaurado) antes da purga."""


class Purga:
    def __init__(
        self,
        repositorio: RepositorioDeJobs,
        correcoes: RepositorioDeCorrecoes,
        arquivos: ArquivosDoJob,
        indice: IndiceDaBusca | None,
        auditoria: RepositorioDeAuditoria,
        relogio: Callable[[], datetime],
    ) -> None:
        self._repositorio = repositorio
        self._correcoes = correcoes
        self._arquivos = arquivos
        self._indice = indice
        self._auditoria = auditoria
        self._relogio = relogio

    def impacto(self, job: Job) -> ImpactoDoVideo:
        return calcular_impacto(job, self._repositorio, self._correcoes, self._arquivos)

    def purgar(self, job_id: str, autor: Usuario | None) -> None:
        """Apaga o vídeo. Sem `autor`, quem purga é a purga automática.

        O registro na auditoria vem antes de apagar: se ele falha, nada é apagado. Se o
        apagamento falha no meio, o Job continua na lixeira e a purga pode ser repetida
        (cada tentativa deixa o próprio registro)."""
        job = self._repositorio.obter(job_id)
        if job is None or job.lixeira is None:
            raise NaoEstaNaLixeira(job_id)
        impacto = self.impacto(job)
        # Com outro Job na mesma chave de conteúdo, o processamento continua para ele.
        compartilhado = bool(impacto.outros_jobs)
        if compartilhado:
            # Os números são do que se apaga: a decupagem e os arquivos ficam.
            impacto = impacto.model_copy(
                update={
                    "decupagem": 0,
                    "arquivos": ArquivosDoImpacto(copia_limpa=0, proxy=0, quadros=0),
                }
            )
        detalhes = impacto.model_dump(mode="json") | {
            "conteudo_compartilhado": compartilhado
        }
        self._auditoria.acrescentar(
            RegistroDeAuditoria(
                id=uuid.uuid4().hex,
                quando=self._relogio(),
                uid=autor.uid if autor else None,
                email=autor.email if autor else None,
                sistema=None if autor else SISTEMA_DA_PURGA,
                acao="item.purgado",
                alvo_tipo="video",
                alvo_id=job.id,
                alvo_nome=job.nome,
                motivo=job.lixeira.motivo,
                detalhes=detalhes,
            )
        )
        self._correcoes.purgar(job.id)
        if not compartilhado:
            self._arquivos.apagar(job.id)
            if self._indice is not None:
                self._indice.apagar(job.id)
        self._repositorio.remover(job.id)


def purgar_vencidas(
    repositorio: RepositorioDeJobs, purga: Purga, agora: datetime
) -> list[str]:
    """Purga o que está na lixeira há `PRAZO_DA_PURGA` ou mais; devolve os ids purgados.
    Um vídeo que falha não impede os outros: fica na lixeira e a próxima execução o tenta."""
    purgados: list[str] = []
    for job in repositorio.consultar(FiltroDeJobs(na_lixeira=True)).jobs:
        if job.lixeira is None or agora - job.lixeira.em < PRAZO_DA_PURGA:
            continue
        try:
            purga.purgar(job.id, None)
        except NaoEstaNaLixeira:
            continue
        except Exception:
            log.exception("a purga de %s falhou", job.id)
            continue
        purgados.append(job.id)
    return purgados


class PedidoDePurga(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # O nome do arquivo, digitado: a prova de que a pessoa sabe o que está apagando.
    nome: str


class VideoPurgado(BaseModel):
    id: str
    nome: str


def criar_rotas_da_purga(
    purga: Purga,
    repositorio: RepositorioDeJobs,
    relogio: Callable[[], datetime],
    login_recente: timedelta = LOGIN_RECENTE_PADRAO,
) -> APIRouter:
    # O parâmetro não se chama `job_id`, como nas outras rotas da lixeira (ver `api.lixeira`).
    rotas = APIRouter(prefix="/admin/lixeira")

    @rotas.post("/videos/{id_do_video}/purgar")
    def purgar(
        id_do_video: str,
        pedido: PedidoDePurga,
        pessoa: Annotated[Usuario, Depends(_exige_gerir)],
    ) -> VideoPurgado:
        if pessoa.login_em is None or relogio() - pessoa.login_em > login_recente:
            raise HTTPException(403, "login_recente_exigido")
        job = repositorio.obter(id_do_video)
        if job is None:
            raise HTTPException(404, "Job não encontrado")
        if job.lixeira is None:
            raise HTTPException(409, "Só se purga o que está na lixeira")
        if pedido.nome != job.nome:
            raise HTTPException(422, "O nome digitado não é o do arquivo")
        try:
            purga.purgar(job.id, pessoa)
        except NaoEstaNaLixeira:
            raise HTTPException(409, "O vídeo saiu da lixeira") from None
        return VideoPurgado(id=job.id, nome=job.nome)

    return rotas


def main(ambiente: Mapping[str, str] = os.environ) -> int:
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        aceitos = exigir_do_ambiente(ambiente, "BUCKET_ACEITOS")
        decupagens = exigir_do_ambiente(ambiente, "BUCKET_DECUPAGENS")
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO)
    cliente = firestore.Client(project=projeto)
    busca = ConfigDaBusca.do_ambiente(ambiente) if "BUSCA_COLECAO" in ambiente else None
    repositorio = RepositorioFirestore(cliente)
    purga = Purga(
        repositorio,
        RepositorioDeCorrecoesFirestore(cliente),
        ArquivosNoStorage(ClienteStorage(project=projeto), aceitos, decupagens),
        AgentRetrieval(busca, transporte_http()) if busca else None,
        RepositorioDeAuditoriaFirestore(cliente),
        agora_utc,
    )
    purgados = purgar_vencidas(repositorio, purga, agora_utc())
    log.info("purga automática: %d vídeo(s) purgado(s)", len(purgados))
    return 0


if __name__ == "__main__":
    sys.exit(main())
