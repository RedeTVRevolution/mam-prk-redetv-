"""Indexa a Decupagem entregue de um Job no índice da busca (#118).

Só o que mudou vai ao índice (#418): `AgentRetrieval.gravar` lê o que o vídeo tem lá, compara com
a Decupagem e apaga, cria ou atualiza só a diferença. Repetir dá o mesmo resultado, e uma
queda no meio termina na rodada seguinte, porque a comparação parte do índice.
Roda ao fim da análise (Job `mam-indexacao`, depois dos quadros-chave), a cada pedido
(aprovar a revisão, trocar o programa: só sobem a `versao_pedida` do Job, #419) e sob
demanda (`make reindexar`); uma execução por vez, a que toma a vez, indexa até a versão pedida. O estado vai no Job
(`indexacao`); uma falha dela só fica ali e nunca muda o `estado` do Job.
"""

import json
import logging
import os
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import datetime
from functools import partial
from typing import Any, NamedTuple, Protocol, get_args

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel

from api import log_estruturado
from api.agent_retrieval import AgentRetrieval, ConfigDaBusca, transporte_http
from api.catalogo import PessoaDoCatalogo
from api.catalogo_apagado import com_pessoas_fundidas
from api.catalogo_dos_jobs import gravar_catalogo_do_job
from api.ciclo_de_vida import fechar_a_rodada, tomar_a_rodada
from api.copia_bigquery import CopiaDosMomentos, copia_do_ambiente, linhas_da_decupagem
from api.correcoes import RepositorioDeCorrecoes, decupagem_entregue, versao_do_modelo
from api.decupagem import Decupagem
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
    ProgramasFirestore,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
    TiposDeObjetoFirestore,
)
from api.orcamento_de_escrita import OrcamentoFirestore
from api.programas import RepositorioDeProgramas, terminar_o_pendente
from api.sinal_do_programa import SinalDoPrograma, sinal_do_ambiente
from api.tipos_de_objeto import TiposDeObjeto

log = logging.getLogger(__name__)


class LeitorDeDecupagem(Protocol):
    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]: ...


def _so_o_esquema(modelo: type[BaseModel], dados: dict[str, Any]) -> dict[str, Any]:
    """`dados` sem o que o esquema da Decupagem não tem.

    A decupagem entregue traz marcas de leitura (`origem`, o `id` posicional do
    comercial) que o esquema do modelo, estrito, recusa e que o índice não usa. O `id`
    de fala e de texto na tela fica: o índice o usa no id do registro (#418).
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


class _Resultado(NamedTuple):
    indexacao: Indexacao
    completo: bool  # indexado e, se há cópia, copiado


def _uma_rodada(
    job: Job,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    indice: IndiceDaBusca,
    relogio: Callable[[], datetime],
    copia: CopiaDosMomentos | None,
    sinal: SinalDoPrograma | None,
    tipos_de_objeto: TiposDeObjeto | None,
    pessoas: Callable[[str], PessoaDoCatalogo | None] | None,
) -> _Resultado:
    """Uma passada pelo índice e pela cópia com o `job` lido agora. Não grava o estado final
    da indexação: quem fecha a rodada o grava. Nunca levanta por falha do índice ou da cópia."""
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
    return _Resultado(
        Indexacao(estado=estado, em=fim, desde=inicio),
        estado == "indexado" and (not copia or estado_da_copia == "copiado"),
    )


def reindexar(
    job: Job,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    indice: IndiceDaBusca,
    relogio: Callable[[], datetime] = agora_utc,
    copia: CopiaDosMomentos | None = None,
    sinal: SinalDoPrograma | None = None,
    tipos_de_objeto: TiposDeObjeto | None = None,
    pessoas: Callable[[str], PessoaDoCatalogo | None] | None = None,
    programas: RepositorioDeProgramas | None = None,
    so_se_pedida: bool = False,
) -> Indexacao | None:
    """Indexa o vídeo (e a cópia do BigQuery) até alcançar a `versao_pedida` e devolve o
    estado da indexação (#419).

    Toma a vez de indexar o vídeo: se outra execução a tem, ou, com `so_se_pedida`, se nada
    foi pedido, devolve `None` sem gravar. O que se pedir durante a rodada é atendido na
    volta, por esta mesma execução. Nunca levanta por falha do índice ou da cópia: cada uma
    fica no seu estado no Job. `None` também se o Job não está `concluido`. Com `sinal`, o
    vídeo copiado é comparado com o histórico do programa (#287); com `tipos_de_objeto`, os
    tipos dos objetos entram no autocompletar (#308); os dois só vão ao log se falham. Com
    `programas`, o vídeo sai dos pendentes da troca de nome do programa ao terminar.
    """
    rodada_id = uuid.uuid4().hex
    try:
        atual = tomar_a_rodada(
            repositorio, job.id, relogio(), rodada_id, so_se_pedida=so_se_pedida
        )
    except Exception:
        log.exception("vez de indexar %s não tomada", job.id)
        return None
    if atual is None:
        return None
    fechado: Job | None = None
    resultado: _Resultado
    while True:
        alvo = atual.versao_pedida
        resultado = _uma_rodada(
            atual,
            repositorio,
            decupagens,
            correcoes,
            indice,
            relogio,
            copia,
            sinal,
            tipos_de_objeto,
            pessoas,
        )
        # Sem fechar, a vez fica presa até `PRAZO_DA_RODADA` e a tela em "Finalizando".
        fechado = _duas_tentativas(
            partial(
                fechar_a_rodada,
                repositorio,
                job.id,
                rodada_id,
                alvo,
                indexado=resultado.indexacao.estado == "indexado",
                indexacao=resultado.indexacao,
                agora=relogio(),
            ),
            f"rodada de {job.id} não fechada",
        )
        if fechado is None or fechado.rodada_da_indexacao is None:
            break
        atual = fechado
    if programas is not None:
        # Sem a segunda tentativa, uma queda passageira deixaria o vídeo pendente (a tela
        # só o resolve com o `retomar`).
        _duas_tentativas(
            lambda: terminar_o_pendente(
                programas, job.id, atual.programa, resultado.completo
            ),
            f"troca de nome do programa não atualizada para {job.id}",
        )
    return fechado.indexacao if fechado else None


def _duas_tentativas[T](acao: Callable[[], T], falha: str) -> T | None:
    """`acao()`, tentada de novo uma vez se levanta; `None` (e o log) se as duas falham."""
    for tentativa in (1, 2):
        try:
            return acao()
        except Exception:
            log.exception("%s (tentativa %d)", falha, tentativa)
    return None


def reindexar_jobs(
    ids: list[str] | None,
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    correcoes: RepositorioDeCorrecoes,
    indice: IndiceDaBusca,
    copia: CopiaDosMomentos | None = None,
    sinal: SinalDoPrograma | None = None,
    tipos_de_objeto: TiposDeObjeto | None = None,
    pessoas: Callable[[str], PessoaDoCatalogo | None] | None = None,
    programas: RepositorioDeProgramas | None = None,
    so_se_pedida: bool = False,
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
            sinal=sinal,
            tipos_de_objeto=tipos_de_objeto,
            pessoas=pessoas,
            programas=programas,
            so_se_pedida=so_se_pedida,
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
        AgentRetrieval(
            busca,
            transporte_http(),
            tentar_no_429=True,
            orcamento=OrcamentoFirestore(firestore_),
        ),
        copia_do_ambiente(os.environ),
        sinal=sinal,
        tipos_de_objeto=TiposDeObjetoFirestore(firestore_),
        pessoas=CatalogoFirestore(firestore_).obter,
        programas=ProgramasFirestore(firestore_),
        # Disparado pelo Workflows/API (JOB_ID, sem argv) só indexa o que se pediu; o
        # `make reindexar` sempre indexa.
        so_se_pedida=not argv and "JOB_ID" in os.environ,
    )
    for job_id, estado in resultado.items():
        print(f"{job_id}: {estado}")
    return 1 if {"falhou", "inexistente"} & set(resultado.values()) else 0


if __name__ == "__main__":
    # Sem isto o Python cai no manejador padrão, em texto puro (#475).
    log_estruturado.configurar(logging.WARNING)
    sys.exit(main(sys.argv[1:]))
