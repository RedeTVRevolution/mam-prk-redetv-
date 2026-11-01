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
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any, Protocol, get_args

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel

from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.correcoes import RepositorioDeCorrecoes, decupagem_entregue, versao_do_modelo
from api.decupagem import Decupagem
from api.indice_da_busca import IndiceDaBusca, registros_da_decupagem
from api.jobs import (
    EstadoDaIndexacao,
    Indexacao,
    Job,
    RepositorioDeJobs,
    agora_utc,
)
from api.nuvem import (
    DecupagensStorage,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
)

log = logging.getLogger(__name__)


class LeitorDeDecupagem(Protocol):
    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]: ...


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
    estado: EstadoDaIndexacao,
    agora: datetime,
) -> Job | None:
    """Grava o estado da indexação sem mudar o `estado` do Job.

    Não é uma transição do ciclo de vida: a troca condicional em `concluido` só garante
    que o Job ainda está lá. Uma falha do repositório vai ao log e devolve `None`, para
    não transformar em erro uma Correção que já foi gravada.
    """
    try:
        return repositorio.transitar(
            job_id, "concluido", {"indexacao": Indexacao(estado=estado, em=agora)}
        )
    except Exception:
        log.exception("estado da indexação não gravado para %s", job_id)
        return None


def reindexar(
    job: Job,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    indice: IndiceDaBusca,
    relogio: Callable[[], datetime] = agora_utc,
) -> Indexacao | None:
    """Regrava o vídeo no índice e devolve o estado novo; nunca levanta por falha do índice.

    `None` se o Job não está `concluido` (não há Decupagem para indexar).
    """
    if job.estado != "concluido":
        return None
    _registrar(repositorio, job.id, "pendente", relogio())
    estado: EstadoDaIndexacao
    try:
        conteudo = b"".join(decupagens.abrir_decupagem(job.id))
        entregue = decupagem_entregue(
            json.loads(conteudo), versao_do_modelo(conteudo), correcoes.listar(job.id)
        )
        registros = registros_da_decupagem(
            job.id,
            Decupagem.model_validate(_so_o_esquema(Decupagem, entregue)),
            job.programa,
            job.data_exibicao,
        )
        indice.gravar(job.id, registros)
        estado = "indexado"
    except Exception:
        log.exception("indexação falhou para %s", job.id)
        estado = "falhou"
    atual = _registrar(repositorio, job.id, estado, relogio())
    return atual.indexacao if atual else None


def reindexar_jobs(
    ids: list[str] | None,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    indice: IndiceDaBusca,
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
        jobs = [j for j in repositorio.listar() if j.estado == "concluido"]
    for job in jobs:
        nova = reindexar(job, repositorio, decupagens, correcoes, indice)
        resultado[job.id] = nova.estado if nova else "ignorado"
    return resultado


def main(argv: list[str]) -> int:
    projeto = os.environ["GCP_PROJECT_ID"]
    firestore_ = firestore.Client(project=projeto)
    resultado = reindexar_jobs(
        argv or ([os.environ["JOB_ID"]] if "JOB_ID" in os.environ else None),
        RepositorioFirestore(firestore_),
        DecupagensStorage(
            ClienteStorage(project=projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        RepositorioDeCorrecoesFirestore(firestore_),
        AgentRetrieval(ConfigDaBusca.do_ambiente(os.environ), transporte_http()),
    )
    for job_id, estado in resultado.items():
        print(f"{job_id}: {estado}")
    return 1 if {"falhou", "inexistente"} & set(resultado.values()) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
