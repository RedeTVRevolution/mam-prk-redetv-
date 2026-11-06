"""Indexa a Decupagem entregue de um Job no índice da busca (#118).

O vídeo inteiro é apagado e regravado a cada vez, então repetir dá o mesmo resultado.
Roda ao fim da análise (Job `mam-indexacao`, depois dos quadros-chave), a cada Correção
que passa a valer (`api.jobs`) e sob demanda (`make reindexar`). O estado vai no Job
(`indexacao`); uma falha dela só fica ali e nunca muda o `estado` do Job.
"""

import json
import logging
import os
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any, Protocol, get_args

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel

from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.catalogo import PessoaDoCatalogo
from api.catalogo_apagado import com_pessoas_fundidas
from api.catalogo_dos_jobs import gravar_catalogo_do_job
from api.copia_bigquery import CopiaDosMomentos, copia_do_ambiente, linhas_da_decupagem
from api.correcoes import RepositorioDeCorrecoes, decupagem_entregue, versao_do_modelo
from api.decupagem import Decupagem
from api.embedding_do_quadro import (
    EmbeddingDoQuadro,
    com_vetores_do_quadro,
    embedding_da_busca,
)
from api.indice_da_busca import IndiceDaBusca, registros_da_decupagem
from api.jobs import (
    CopiaNoBigQuery,
    EstadoDaCopia,
    EstadoDaIndexacao,
    Indexacao,
    Job,
    RepositorioDeJobs,
    agora_utc,
)
from api.nuvem import (
    CatalogoFirestore,
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
    TiposDeObjetoFirestore,
)
from api.sinal_do_programa import SinalDoPrograma, sinal_do_ambiente
from api.tipos_de_objeto import TiposDeObjeto

log = logging.getLogger(__name__)


class LeitorDeDecupagem(Protocol):
    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]: ...


class LeitorDeQuadros(Protocol):
    def ler_quadro(self, job_id: str, caminho: str) -> bytes: ...


def _so_o_esquema(modelo: type[BaseModel], dados: dict[str, Any]) -> dict[str, Any]:
    """`dados` sem o que o esquema da Decupagem não tem.

    A decupagem entregue traz marcas de leitura (`origem`, o `id` posicional) que o
    esquema do modelo, estrito, recusa e que o índice não usa.
    """
    podado: dict[str, Any] = {}
    for nome, valor in dados.items():
        campo = modelo.model_fields.get(nome)
        if campo is None:
            continue
        filho = next(
            (
                t
                for t in (campo.annotation, *get_args(campo.annotation))
                + tuple(a for t in get_args(campo.annotation) for a in get_args(t))
                if isinstance(t, type) and issubclass(t, BaseModel)
            ),
            None,
        )
        if filho is not None and isinstance(valor, dict):
            valor = _so_o_esquema(filho, valor)
        elif filho is not None and isinstance(valor, list):
            valor = [
                _so_o_esquema(filho, v) if isinstance(v, dict) else v for v in valor
            ]
        podado[nome] = valor
    return podado


def _registrar(
    repositorio: RepositorioDeJobs,
    job_id: str,
    campo: str,
    valor: Indexacao | CopiaNoBigQuery,
) -> Job | None:
    """Grava o estado da indexação (ou da cópia) sem mudar o `estado` do Job.

    Não é uma transição do ciclo de vida: a troca condicional em `concluido` só garante
    que o Job ainda está lá. Uma falha do repositório vai ao log e devolve `None`, para
    não transformar em erro uma Correção que já foi gravada.
    """
    try:
        return repositorio.transitar(job_id, "concluido", {campo: valor})
    except Exception:
        log.exception("estado de %s não gravado para %s", campo, job_id)
        return None


def decupagem_do_job(
    job: Job,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    pessoas: Callable[[str], PessoaDoCatalogo | None] | None = None,
) -> Decupagem:
    """A Decupagem entregue (com as Correções em vigor), no esquema do modelo. Com
    `pessoas`, o catálogo manda no nome e no id de quem foi fundido ou renomeado (#209, #263)."""
    conteudo = b"".join(decupagens.abrir_decupagem(job.id))
    entregue = decupagem_entregue(
        json.loads(conteudo), versao_do_modelo(conteudo), correcoes.listar(job.id)
    )
    if pessoas is not None:
        entregue = com_pessoas_fundidas(entregue, pessoas)
    return Decupagem.model_validate(_so_o_esquema(Decupagem, entregue))


def reindexar(
    job: Job,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    indice: IndiceDaBusca,
    relogio: Callable[[], datetime] = agora_utc,
    copia: CopiaDosMomentos | None = None,
    embedding: EmbeddingDoQuadro | None = None,
    quadros: LeitorDeQuadros | None = None,
    sinal: SinalDoPrograma | None = None,
    tipos_de_objeto: TiposDeObjeto | None = None,
    pessoas: Callable[[str], PessoaDoCatalogo | None] | None = None,
) -> Indexacao | None:
    """Regrava o vídeo no índice (e na cópia do BigQuery) e devolve o estado da indexação.

    Nunca levanta por falha do índice ou da cópia: cada uma fica no seu estado no Job, e
    uma não impede a outra. Com `embedding` e `quadros` (o índice do quadro-chave ligado,
    ADR 0006), cada plano com quadro leva o vetor multimodal. `None` se o Job não está
    `concluido` (não há Decupagem). Com `sinal`, o vídeo copiado é comparado com o histórico
    do programa (#287); o sinal também nunca levanta. Com `tipos_de_objeto`, os tipos dos
    objetos da Decupagem entram na lista do autocompletar (#308); falha só vai ao log.
    """
    if job.estado != "concluido":
        return None
    inicio = relogio()
    _registrar(
        repositorio, job.id, "indexacao", Indexacao(estado="pendente", em=inicio)
    )
    if copia:
        _registrar(
            repositorio,
            job.id,
            "copia_bigquery",
            CopiaNoBigQuery(estado="pendente", em=inicio),
        )
    estado: EstadoDaIndexacao = "falhou"
    estado_da_copia: EstadoDaCopia = "falhou"
    try:
        decupagem = decupagem_do_job(job, decupagens, correcoes, pessoas)
    except Exception:
        log.exception("decupagem de %s não lida para indexar", job.id)
    else:
        gravar_catalogo_do_job(repositorio, job.id, decupagem.model_dump())
        if tipos_de_objeto:
            try:
                tipos_de_objeto.registrar(
                    job.id, Counter(o.tipo for o in decupagem.objetos)
                )
            except Exception:
                log.exception("tipos de objeto de %s não registrados", job.id)
        try:
            registros = registros_da_decupagem(
                job.id, decupagem, job.programa, job.data_exibicao
            )
            if embedding and quadros:
                registros = com_vetores_do_quadro(
                    registros,
                    lambda caminho: quadros.ler_quadro(job.id, caminho),
                    embedding,
                )
            indice.gravar(job.id, registros)
            estado = "indexado"
        except Exception:
            log.exception("indexação falhou para %s", job.id)
        if copia:
            try:
                linhas = linhas_da_decupagem(
                    job.id, decupagem, job.programa, job.data_exibicao, inicio
                )
                copia.gravar(job.id, linhas)
                estado_da_copia = "copiado"
            except Exception:
                log.exception("cópia para o BigQuery falhou para %s", job.id)
            else:
                if sinal:
                    try:
                        sinal.avaliar(job.id, job.programa, linhas)
                    except Exception:
                        log.exception("sinal por programa falhou para %s", job.id)
    fim = relogio()
    if copia:
        _registrar(
            repositorio,
            job.id,
            "copia_bigquery",
            CopiaNoBigQuery(estado=estado_da_copia, em=fim, desde=inicio),
        )
    atual = _registrar(
        repositorio, job.id, "indexacao", Indexacao(estado=estado, em=fim, desde=inicio)
    )
    return atual.indexacao if atual else None


def reindexar_jobs(
    ids: list[str] | None,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    indice: IndiceDaBusca,
    copia: CopiaDosMomentos | None = None,
    embedding: EmbeddingDoQuadro | None = None,
    quadros: LeitorDeQuadros | None = None,
    sinal: SinalDoPrograma | None = None,
    tipos_de_objeto: TiposDeObjeto | None = None,
    pessoas: Callable[[str], PessoaDoCatalogo | None] | None = None,
) -> dict[str, str]:
    """Reindexa os Jobs de `ids`, ou todos os concluídos; devolve o estado de cada um.

    Um id que não existe sai como `inexistente`.
    """
    resultado: dict[str, str] = {}
    if ids:
        jobs = []
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
        nova = reindexar(
            job,
            repositorio,
            decupagens,
            correcoes,
            indice,
            copia=copia,
            embedding=embedding,
            quadros=quadros,
            sinal=sinal,
            tipos_de_objeto=tipos_de_objeto,
            pessoas=pessoas,
        )
        resultado[job.id] = nova.estado if nova else "ignorado"
    return resultado


def main(argv: list[str]) -> int:
    projeto = os.environ["GCP_PROJECT_ID"]
    firestore_ = firestore.Client(project=projeto)
    decupagens = DecupagensStorage(
        ClienteStorage(project=projeto),
        os.environ["BUCKET_ACEITOS"],
        os.environ["BUCKET_DECUPAGENS"],
    )
    busca = ConfigDaBusca.do_ambiente(os.environ)
    # O sinal por programa só vale para o vídeo que acabou de concluir (o Workflows passa
    # JOB_ID); reindexar todos os vídeos de uma vez não o avalia, para não alertar o passado.
    sinal = (
        sinal_do_ambiente(os.environ) if not argv and "JOB_ID" in os.environ else None
    )
    resultado = reindexar_jobs(
        argv or ([os.environ["JOB_ID"]] if "JOB_ID" in os.environ else None),
        RepositorioFirestore(firestore_),
        decupagens,
        RepositorioDeCorrecoesFirestore(firestore_),
        AgentRetrieval(busca, transporte_http(), tentar_no_429=True),
        copia_do_ambiente(os.environ),
        embedding=embedding_da_busca(busca),
        quadros=decupagens,
        sinal=sinal,
        tipos_de_objeto=TiposDeObjetoFirestore(firestore_),
        pessoas=CatalogoFirestore(firestore_).obter,
    )
    for job_id, estado in resultado.items():
        print(f"{job_id}: {estado}")
    return 1 if {"falhou", "inexistente"} & set(resultado.values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
