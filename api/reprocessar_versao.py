"""Reprocessar o acervo de propósito (#250): `make reprocessar-versao`.

Lista os Jobs concluídos de uma `versao_pipeline` (gravada no Job, #494) diferente da atual
(`api/versao_pipeline.py`) e, com `CONFIRMAR=1`, reprocessa cada um pela análise, pelo
mesmo caminho da rota do reprocessar (#147, #235): Job, auditoria e Workflows. Sem
`CONFIRMAR=1`, só mostra a lista e o custo estimado.

Ambiente: `GCP_PROJECT_ID`, `BUCKET_ACEITOS`, `BUCKET_DECUPAGENS`, `WORKFLOW_REGIAO`,
`WORKFLOW_VALIDACAO`; `CUSTO_POR_HORA_USD` (opcional, o custo de uma hora de vídeo na
análise: sem ele o custo sai "n/d"); `TAMANHO_DO_LOTE` (5) e `PAUSA_ENTRE_LOTES_S` (60).
Argumentos: `DE` (uma versão, ou `anterior` para a decupagem sem o campo) e `LIMITE`.
"""

import json
import logging
import os
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from google.cloud.storage import Client as ClienteStorage

from api.auditoria import RepositorioDeAuditoria
from api.bancos import cliente_da_colecao, cliente_do_firestore
from api.ciclo_de_vida import NaoReprocessavel
from api.comparar_objetos import FaltaNoAmbiente, exigir_do_ambiente
from api.jobs import (
    FiltroDeJobs,
    Job,
    RepositorioDeJobs,
    ServicoIndisponivel,
    agora_utc,
)
from api.nuvem import (
    COLECAO_DA_AUDITORIA,
    DecupagensStorage,
    DisparoPeloWorkflows,
    JanelasStorage,
    RepositorioDeAuditoriaFirestore,
    RepositorioFirestore,
)
from api.progresso_das_janelas import JanelasDoJob
from api.reprocessamento import DisparoDoWorkflow, reprocessar_com_rastro
from api.versao_pipeline import VERSAO_PIPELINE

log = logging.getLogger(__name__)

ANTERIOR = "anterior"
SISTEMA = "reprocessar-versao"
MOTIVO = "versão nova do pipeline"
LOTE = 5
PAUSA_ENTRE_LOTES_S = 60.0
TAMANHO_DA_PAGINA = 500

__all__ = ["escolher", "main", "reprocessar_versao", "versao_da_decupagem"]


class LeitorDeDecupagem(Protocol):
    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]: ...


@dataclass(frozen=True)
class Candidato:
    job_id: str
    nome: str
    versao: str
    duracao_s: float | None


def versao_da_decupagem(decupagens: LeitorDeDecupagem, job_id: str) -> str | None:
    """A `versao_pipeline` gravada, `ANTERIOR` se não há o campo, `None` se não leu."""
    try:
        dados = json.loads(b"".join(decupagens.abrir_decupagem(job_id)))
    except (ServicoIndisponivel, ValueError):
        log.warning("decupagem de %s não lida: fora da lista", job_id)
        return None
    return str(dados.get("versao_pipeline") or ANTERIOR)


def _concluidos(
    repositorio: RepositorioDeJobs, tamanho_da_pagina: int
) -> Iterator[Job]:
    """Os Jobs concluídos fora da lixeira, página a página, sem baixar decupagem."""
    cursor: str | None = None
    while True:
        lida = repositorio.consultar(
            FiltroDeJobs(
                estados=frozenset({"concluido"}),
                limite=tamanho_da_pagina,
                cursor=cursor,
            )
        )
        yield from lida.jobs
        cursor = lida.proximo_cursor
        if cursor is None:
            return


def escolher(
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    de: str | None,
    limite: int | None,
    tamanho_da_pagina: int = TAMANHO_DA_PAGINA,
) -> list[Candidato]:
    """Os Jobs concluídos de versão anterior, do mais antigo ao mais novo, até `limite`.

    A versão vem do Job (#494). Só o Job sem o campo (anterior a `make gravar-versao-nos-jobs`)
    abre a decupagem, e continua na lista como versão desconhecida se ela não for lida.
    """
    concluidos = sorted(
        _concluidos(repositorio, tamanho_da_pagina), key=lambda j: (j.criado_em, j.id)
    )
    escolhidos: list[Candidato] = []
    for job in concluidos:
        if limite is not None and len(escolhidos) >= limite:
            break
        versao = job.versao_pipeline or versao_da_decupagem(decupagens, job.id)
        if versao is None or versao == VERSAO_PIPELINE:
            continue
        if de is not None and versao != de:
            continue
        escolhidos.append(Candidato(job.id, job.nome, versao, job.duracao_s))
    return escolhidos


def _dolar(valor: float) -> str:
    return f"US$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def reprocessar_versao(
    repositorio: RepositorioDeJobs,
    decupagens: LeitorDeDecupagem,
    auditoria: RepositorioDeAuditoria,
    disparo: DisparoDoWorkflow,
    janelas: JanelasDoJob | None,
    *,
    de: str | None = None,
    limite: int | None = None,
    confirmar: bool = False,
    custo_por_hora: float | None = None,
    tamanho_do_lote: int = LOTE,
    pausa_s: float = PAUSA_ENTRE_LOTES_S,
    relogio: Callable[[], datetime] = agora_utc,
    dormir: Callable[[float], None] = time.sleep,
    escrever: Callable[[str], None] = print,
) -> None:
    escolhidos = escolher(repositorio, decupagens, de, limite)
    horas = sum(c.duracao_s or 0 for c in escolhidos) / 3600
    sem_duracao = sum(1 for c in escolhidos if c.duracao_s is None)
    custo = "n/d" if custo_por_hora is None else _dolar(horas * custo_por_hora)
    escrever(f"Versão do pipeline: {VERSAO_PIPELINE}")
    for c in escolhidos:
        duracao = (
            "duração n/d" if c.duracao_s is None else f"{c.duracao_s / 3600:.2f} h"
        )
        escrever(f"{c.job_id}  {c.nome}  versão {c.versao}  {duracao}")
    escrever(f"{len(escolhidos)} Jobs, {horas:.2f} h de vídeo, custo estimado {custo}")
    if sem_duracao:
        escrever(f"{sem_duracao} Jobs sem duração ficaram fora das horas e do custo.")
    if not confirmar:
        escrever("Nada foi reprocessado: rode de novo com CONFIRMAR=1.")
        return
    for inicio in range(0, len(escolhidos), tamanho_do_lote):
        if inicio:
            dormir(pausa_s)
        for c in escolhidos[inicio : inicio + tamanho_do_lote]:
            escrever(
                f"{c.job_id}: {_reprocessar(c, repositorio, auditoria, disparo, janelas, relogio)}"
            )


def _reprocessar(
    c: Candidato,
    repositorio: RepositorioDeJobs,
    auditoria: RepositorioDeAuditoria,
    disparo: DisparoDoWorkflow,
    janelas: JanelasDoJob | None,
    relogio: Callable[[], datetime],
) -> str:
    try:
        job: Job | None = reprocessar_com_rastro(
            repositorio,
            auditoria,
            disparo,
            janelas,
            c.job_id,
            relogio(),
            "analise",
            autor={"sistema": SISTEMA},
            motivo=MOTIVO,
            relogio=relogio,
        )
    except NaoReprocessavel as erro:
        return f"ignorado ({erro})"
    except Exception:
        log.exception("reprocessar %s falhou", c.job_id)
        return "falhou"
    return "reprocessando" if job else "inexistente"


def main(argumentos: list[str], ambiente: Mapping[str, str] = os.environ) -> int:
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        aceitos = exigir_do_ambiente(ambiente, "BUCKET_ACEITOS")
        decupagens = exigir_do_ambiente(ambiente, "BUCKET_DECUPAGENS")
        regiao = exigir_do_ambiente(ambiente, "WORKFLOW_REGIAO")
        workflow = exigir_do_ambiente(ambiente, "WORKFLOW_VALIDACAO")
        de = argumentos[0] if argumentos and argumentos[0] else None
        limite = int(argumentos[1]) if len(argumentos) > 1 and argumentos[1] else None
        custo = ambiente.get("CUSTO_POR_HORA_USD")
        custo_por_hora = float(custo) if custo else None
        tamanho_do_lote = int(ambiente.get("TAMANHO_DO_LOTE") or LOTE)
        pausa_s = float(ambiente.get("PAUSA_ENTRE_LOTES_S") or PAUSA_ENTRE_LOTES_S)
    except (FaltaNoAmbiente, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    banco = cliente_do_firestore(projeto, ambiente)
    cliente = ClienteStorage(project=projeto)
    reprocessar_versao(
        RepositorioFirestore(banco),
        DecupagensStorage(cliente, aceitos, decupagens),
        RepositorioDeAuditoriaFirestore(
            cliente_da_colecao(projeto, COLECAO_DA_AUDITORIA, ambiente)
        ),
        DisparoPeloWorkflows(projeto, regiao, workflow),
        JanelasStorage(cliente, aceitos),
        de=de,
        limite=limite,
        confirmar=ambiente.get("CONFIRMAR") == "1",
        custo_por_hora=custo_por_hora,
        tamanho_do_lote=tamanho_do_lote,
        pausa_s=pausa_s,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
