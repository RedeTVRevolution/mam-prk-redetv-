"""Correção manual do estado de um Job (#289), só para o Administrador.

A rota `POST /v1/admin/jobs/{id}/estado` e o comando `make corrigir-estado` passam pela
mesma função, `corrigir_estado_com_rastro`: muda o Job pelo ciclo de vida (que decide o
que é permitido) e registra na auditoria o estado antigo, o novo, o motivo e quem fez.
O Job muda antes do registro; se o registro falha, o Job volta ao que era.

Comando: `make corrigir-estado JOB=... ESTADO=... MOTIVO=...`. Ambiente:
`GCP_PROJECT_ID`, `BUCKET_ACEITOS` e `BUCKET_DECUPAGENS`.
"""

import getpass
import os
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from typing import Annotated, Protocol, cast, get_args

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from api.auditoria import RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.ciclo_de_vida import (
    DestinoDaCorrecao,
    EstadoNaoCorrigivel,
    corrigir_estado,
    desfazer_correcao,
)
from api.comparar_objetos import FaltaNoAmbiente, exigir_do_ambiente
from api.decupagem import Decupagem
from api.jobs import (
    Job,
    JobPublico,
    RepositorioDeJobs,
    ServicoIndisponivel,
    _confere_permissao,
    agora_utc,
)

SISTEMA = "corrigir-estado"
MOTIVO_MAXIMO = 500


class LeitorDeDecupagem(Protocol):
    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]: ...


def tem_decupagem_completa(leitor: LeitorDeDecupagem, job_id: str) -> bool:
    """A decupagem guardada existe e passa pelo esquema inteiro."""
    try:
        Decupagem.model_validate_json(b"".join(leitor.abrir_decupagem(job_id)))
    except (ServicoIndisponivel, ValidationError):
        return False
    return True


def corrigir_estado_com_rastro(
    repositorio: RepositorioDeJobs,
    auditoria: RepositorioDeAuditoria,
    leitor: LeitorDeDecupagem,
    job_id: str,
    destino: DestinoDaCorrecao,
    motivo: str,
    agora: datetime,
    *,
    autor: dict[str, str],
) -> Job | None:
    """O Job de depois, ou `None` se não existe. `EstadoNaoCorrigivel` sobe.
    `autor` é `uid` e `email` ou `sistema`."""
    trocado = corrigir_estado(
        repositorio,
        job_id,
        destino,
        agora,
        decupagem_completa=destino == "concluido"
        and tem_decupagem_completa(leitor, job_id),
    )
    if trocado is None:
        return None
    antes, depois = trocado
    try:
        auditoria.acrescentar(
            RegistroDeAuditoria(
                id=uuid.uuid4().hex,
                quando=agora,
                **autor,
                acao="job.estado_corrigido",
                alvo_tipo="job",
                alvo_id=depois.id,
                alvo_nome=depois.nome,
                motivo=motivo,
                detalhes={"de": antes.estado, "para": depois.estado},
            )
        )
    except Exception:
        desfazer_correcao(repositorio, antes, depois, agora)
        raise
    return depois


class PedidoDeCorrecao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    estado: DestinoDaCorrecao
    motivo: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MOTIVO_MAXIMO
        ),
    ]


def _exige_corrigir_estado(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `job.corrigir_estado` (o Administrador)."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não corrige o estado")
    _confere_permissao(request, chamador, "job.corrigir_estado")
    return chamador


def criar_rotas_da_correcao_de_estado(
    repositorio: RepositorioDeJobs,
    auditoria: RepositorioDeAuditoria,
    leitor: LeitorDeDecupagem,
    relogio: Callable[[], datetime],
) -> APIRouter:
    rotas = APIRouter(prefix="/admin/jobs")

    @rotas.post("/{job_id}/estado")
    def corrigir(
        job_id: str,
        pedido: PedidoDeCorrecao,
        pessoa: Annotated[Usuario, Depends(_exige_corrigir_estado)],
    ) -> JobPublico:
        try:
            job = corrigir_estado_com_rastro(
                repositorio,
                auditoria,
                leitor,
                job_id,
                pedido.estado,
                pedido.motivo,
                relogio(),
                autor={"uid": pessoa.uid, "email": pessoa.email},
            )
        except EstadoNaoCorrigivel as erro:
            raise HTTPException(409, str(erro)) from None
        if job is None:
            raise HTTPException(404, "Job não encontrado")
        return JobPublico.de(job)

    return rotas


def main(
    argumentos: list[str],
    repositorio: RepositorioDeJobs,
    auditoria: RepositorioDeAuditoria,
    leitor: LeitorDeDecupagem,
    *,
    relogio: Callable[[], datetime] = agora_utc,
    quem: str | None = None,
    escrever: Callable[[str], None] = print,
) -> int:
    """0 se corrigiu; 2 se os argumentos não servem; 1 se a correção foi recusada."""
    if len(argumentos) != 3:
        escrever("uso: corrigir-estado JOB ESTADO MOTIVO")
        return 2
    job_id, estado, motivo = (a.strip() for a in argumentos)
    if not job_id or not motivo or estado not in get_args(DestinoDaCorrecao):
        escrever("erro: informe JOB, ESTADO (concluido ou falhou) e MOTIVO")
        return 2
    try:
        job = corrigir_estado_com_rastro(
            repositorio,
            auditoria,
            leitor,
            job_id,
            cast(DestinoDaCorrecao, estado),
            motivo,
            relogio(),
            autor={"sistema": f"{SISTEMA}:{quem or getpass.getuser()}"},
        )
    except EstadoNaoCorrigivel as erro:
        escrever(f"recusado: {erro}")
        return 1
    if job is None:
        escrever(f"erro: Job {job_id} não encontrado")
        return 1
    escrever(f"{job_id}: agora {job.estado}")
    if job.estado == "concluido":
        escrever("para entrar na busca, reprocesse a partir da indexação")
    return 0


def _do_ambiente(argumentos: list[str], ambiente: Mapping[str, str]) -> int:
    from google.cloud import firestore
    from google.cloud.storage import Client as ClienteStorage

    from api.nuvem import (
        DecupagensStorage,
        RepositorioDeAuditoriaFirestore,
        RepositorioFirestore,
    )

    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        aceitos = exigir_do_ambiente(ambiente, "BUCKET_ACEITOS")
        decupagens = exigir_do_ambiente(ambiente, "BUCKET_DECUPAGENS")
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    banco = firestore.Client(project=projeto)
    return main(
        argumentos,
        RepositorioFirestore(banco),
        RepositorioDeAuditoriaFirestore(banco),
        DecupagensStorage(ClienteStorage(project=projeto), aceitos, decupagens),
    )


if __name__ == "__main__":
    sys.exit(_do_ambiente(sys.argv[1:], os.environ))
