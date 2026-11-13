"""Purga dos vídeos na lixeira (E8): apaga todo o vídeo (ADR 0010).

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
from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel, ConfigDict

from api import log_estruturado
from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.auditoria import RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import Usuario
from api.bancos import cliente_da_colecao, cliente_do_firestore
from api.comparar_objetos import FaltaNoAmbiente, exigir_do_ambiente
from api.correcoes import RepositorioDeCorrecoes
from api.dados_da_purga import dados_do_ambiente
from api.indice_da_busca import IndiceDaBusca
from api.jobs import (
    Armazenamento,
    FiltroDeJobs,
    Job,
    RepositorioDeJobs,
    agora_utc,
    expirar_uploads,
)
from api.lixeira import (
    PRAZO_DA_PURGA,
    ArquivosDoJob,
    ImpactoDoVideo,
    _exige_gerir,
    calcular_impacto,
    login_recente_ou_403,
)
from api.lixeira_do_catalogo import purgar_catalogo_vencido
from api.lixeira_na_leitura import PurgasDeMarcaFirestore, VersaoDaLixeiraFirestore
from api.nuvem import (
    COLECAO_DA_AUDITORIA,
    ArmazenamentoStorage,
    ArquivosNoStorage,
    CatalogoDeMarcasFirestore,
    CatalogoFirestore,
    RepositorioDeAuditoriaFirestore,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
)
from api.orcamento_de_escrita import OrcamentoFirestore
from api.texto_como_dado import Linha

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
        apagar_dados: Callable[[str], None] | None = None,
    ) -> None:
        self._repositorio = repositorio
        self._correcoes = correcoes
        self._arquivos = arquivos
        self._indice = indice
        self._auditoria = auditoria
        self._relogio = relogio
        self._apagar_dados = apagar_dados

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
                detalhes=impacto.model_dump(mode="json"),
            )
        )
        if self._apagar_dados is not None:
            self._apagar_dados(job.id)
        self._correcoes.purgar(job.id)
        # Cada Job tem os próprios arquivos e trechos, mesmo com SHA-256 igual.
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
    nome: Annotated[str, Linha(255)]


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
        login_recente_ou_403(pessoa, relogio(), login_recente)
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


def rodar_a_varredura_diaria(
    repositorio: RepositorioDeJobs,
    purga: Purga,
    armazenamento: Armazenamento,
    purgar_catalogo: Callable[[], int],
    agora: datetime,
) -> None:
    """O que o agendador diário faz: expira uploads abandonados (#369), purga vídeos e catálogo."""
    try:
        expirados = expirar_uploads(repositorio, armazenamento, agora)
        log.info("varredura diária: %d upload(s) expirado(s)", len(expirados))
    except Exception:
        # Não segura a purga: a varredura de amanhã tenta de novo.
        log.exception("a expiração dos uploads falhou")
    purgados = purgar_vencidas(repositorio, purga, agora)
    log.info("purga automática: %d vídeo(s) purgado(s)", len(purgados))
    log.info("purga automática: %d item(ns) do catálogo purgado(s)", purgar_catalogo())


def main(ambiente: Mapping[str, str] = os.environ) -> int:
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        quarentena = exigir_do_ambiente(ambiente, "BUCKET_QUARENTENA")
        aceitos = exigir_do_ambiente(ambiente, "BUCKET_ACEITOS")
        decupagens = exigir_do_ambiente(ambiente, "BUCKET_DECUPAGENS")
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    log_estruturado.configurar(logging.INFO)
    cliente = cliente_do_firestore(projeto, ambiente)
    banco_de_seguranca = cliente_da_colecao(projeto, COLECAO_DA_AUDITORIA, ambiente)
    busca = ConfigDaBusca.do_ambiente(ambiente) if "BUSCA_COLECAO" in ambiente else None
    repositorio = RepositorioFirestore(cliente)
    purga = Purga(
        repositorio,
        RepositorioDeCorrecoesFirestore(cliente),
        ArquivosNoStorage(ClienteStorage(project=projeto), aceitos, decupagens),
        (
            AgentRetrieval(
                busca,
                transporte_http(),
                tentar_no_429=True,
                orcamento=OrcamentoFirestore(cliente),
            )
            if busca
            else None
        ),
        RepositorioDeAuditoriaFirestore(banco_de_seguranca),
        agora_utc,
        apagar_dados=dados_do_ambiente(cliente, ambiente).apagar,
    )
    rodar_a_varredura_diaria(
        repositorio,
        purga,
        ArmazenamentoStorage(
            ClienteStorage(project=projeto), quarentena, aceitos, decupagens
        ),
        lambda: purgar_catalogo_vencido(
            CatalogoFirestore(cliente),
            CatalogoDeMarcasFirestore(cliente),
            RepositorioDeAuditoriaFirestore(banco_de_seguranca),
            agora_utc(),
            PurgasDeMarcaFirestore(cliente),
            VersaoDaLixeiraFirestore(cliente).avancar,
        ),
        agora_utc(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
