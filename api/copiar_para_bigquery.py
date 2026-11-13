"""Carga das decupagens que já existem no BigQuery (#260): `make copiar-para-bigquery [JOB=...]`.

Só a cópia; pedidos de indexação pendentes são atendidos ao soltar a vez.
Grava o estado da cópia no Job, como a indexação; repetir dá o mesmo resultado.
"""

import logging
import os
import sys
import uuid
from collections.abc import Callable
from datetime import datetime
from functools import partial

from google.cloud.storage import Client as ClienteStorage

from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.bancos import cliente_do_firestore
from api.ciclo_de_vida import fechar_a_rodada, tomar_a_rodada
from api.copia_bigquery import (
    CopiaDosMomentos,
    copia_do_ambiente,
    linhas_da_decupagem,
)
from api.correcoes import RepositorioDeCorrecoes
from api.indexacao import (
    LeitorDeDecupagem,
    _duas_tentativas,
    _registrar,
    decupagem_do_job,
    reindexar,
)
from api.indice_da_busca import IndiceDaBusca
from api.jobs import CopiaNoBigQuery, EstadoDaCopia, Job, RepositorioDeJobs, agora_utc
from api.leitura_da_decupagem import MarcasEmLote, PessoasEmLote
from api.nuvem import (
    CatalogoDeMarcasFirestore,
    CatalogoFirestore,
    DecupagensStorage,
    ProgramasFirestore,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
    TiposDeObjetoFirestore,
)
from api.orcamento_de_escrita import OrcamentoFirestore
from api.programas import RepositorioDeProgramas
from api.sinal_do_programa import SinalDoPrograma, sinal_do_ambiente
from api.tipos_de_objeto import TiposDeObjeto

log = logging.getLogger(__name__)


def copiar(
    job: Job,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    copia: CopiaDosMomentos,
    relogio: Callable[[], datetime] = agora_utc,
    pessoas: PessoasEmLote | None = None,
    *,
    marcas: MarcasEmLote | None = None,
    indice: IndiceDaBusca,
    programas: RepositorioDeProgramas | None = None,
    tipos_de_objeto: TiposDeObjeto | None = None,
    sinal: SinalDoPrograma | None = None,
) -> str:
    """Copia o vídeo e devolve o estado: `copiado`, `falhou` ou `ignorado` (sem a vez)."""
    rodada_id = uuid.uuid4().hex
    try:
        atual = tomar_a_rodada(repositorio, job.id, relogio(), rodada_id, so_copia=True)
    except Exception:
        log.exception("vez de copiar %s não tomada", job.id)
        return "falhou"
    if atual is None:
        return "ignorado"
    job = atual
    try:
        inicio = relogio()
        ultima_copia = job.copia_bigquery or CopiaNoBigQuery(
            estado="pendente", em=inicio
        )
        pendente = _registrar(
            repositorio,
            job.id,
            "copia_bigquery",
            ultima_copia.model_copy(
                update={"estado": "pendente", "em": inicio, "desde": None}
            ),
        )
        estado: EstadoDaCopia = "copiado"
        try:
            decupagem = decupagem_do_job(job, decupagens, correcoes, pessoas, marcas)
            if pendente is None:
                raise RuntimeError("estado pendente da cópia não gravado")
            ultima_copia = pendente.copia_bigquery or CopiaNoBigQuery(
                estado="pendente", em=inicio
            )
            if job.data_exibicao:
                ano = job.data_exibicao.year
                ultima_copia = ultima_copia.model_copy(
                    update={"anos": sorted(set(ultima_copia.anos) | {ano})}
                )
                repositorio.acrescentar_ano_da_copia(job.id, ano)
            copia.gravar(
                job.id,
                linhas_da_decupagem(
                    job.id, decupagem, job.programa, job.data_exibicao, inicio
                ),
                anos=ultima_copia.anos if ultima_copia.particoes_conhecidas else None,
            )
        except Exception:
            log.exception("cópia para o BigQuery falhou para %s", job.id)
            estado = "falhou"
        _registrar(
            repositorio,
            job.id,
            "copia_bigquery",
            ultima_copia.model_copy(
                update={"estado": estado, "em": relogio(), "desde": inicio}
            ),
        )
        return estado
    finally:
        fechado = _duas_tentativas(
            partial(
                fechar_a_rodada,
                repositorio,
                job.id,
                rodada_id,
                job.versao_pedida,
                indexado=False,
                indexacao=job.indexacao,
                agora=relogio(),
                so_copia=True,
            ),
            f"rodada da cópia de {job.id} não fechada",
        )
        if fechado:
            reindexar(
                fechado,
                repositorio,
                decupagens,
                correcoes,
                indice,
                relogio=relogio,
                copia=copia,
                pessoas=pessoas,
                marcas=marcas,
                programas=programas,
                tipos_de_objeto=tipos_de_objeto,
                sinal=sinal,
                so_se_pedida=True,
            )


def copiar_jobs(
    ids: list[str] | None,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    copia: CopiaDosMomentos,
    pessoas: PessoasEmLote | None = None,
    *,
    marcas: MarcasEmLote | None = None,
    indice: IndiceDaBusca,
    programas: RepositorioDeProgramas | None = None,
    tipos_de_objeto: TiposDeObjeto | None = None,
    sinal: SinalDoPrograma | None = None,
) -> dict[str, str]:
    """Copia os Jobs de `ids`, ou todos os concluídos; devolve o estado de cada um."""
    resultado: dict[str, str] = {}
    jobs: list[Job] = []
    if ids:
        for i in ids:
            if (job := repositorio.obter(i)) is None:
                resultado[i] = "inexistente"
            else:
                jobs.append(job)
    else:
        jobs = [
            j
            for j in repositorio.listar()
            if j.estado == "concluido" and j.lixeira is None
        ]
    for job in jobs:
        resultado[job.id] = copiar(
            job,
            repositorio,
            decupagens,
            correcoes,
            copia,
            pessoas=pessoas,
            marcas=marcas,
            indice=indice,
            programas=programas,
            tipos_de_objeto=tipos_de_objeto,
            sinal=sinal,
        )
    return resultado


def main(argv: list[str]) -> int:
    copia = copia_do_ambiente(os.environ)
    if copia is None:
        print("BIGQUERY_DATASET não definido", file=sys.stderr)
        return 2
    projeto = os.environ["GCP_PROJECT_ID"]
    firestore_ = cliente_do_firestore(projeto)
    resultado = copiar_jobs(
        argv or None,
        RepositorioFirestore(firestore_),
        DecupagensStorage(
            ClienteStorage(project=projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        RepositorioDeCorrecoesFirestore(firestore_),
        copia,
        pessoas=CatalogoFirestore(firestore_),
        marcas=CatalogoDeMarcasFirestore(firestore_),
        programas=ProgramasFirestore(firestore_),
        tipos_de_objeto=TiposDeObjetoFirestore(firestore_),
        sinal=sinal_do_ambiente(os.environ),
        indice=AgentRetrieval(
            ConfigDaBusca.do_ambiente(os.environ),
            transporte_http(),
            tentar_no_429=True,
            orcamento=OrcamentoFirestore(firestore_),
        ),
    )
    for job_id, estado in resultado.items():
        print(f"{job_id}: {estado}")
    return 1 if {"falhou", "inexistente"} & set(resultado.values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
