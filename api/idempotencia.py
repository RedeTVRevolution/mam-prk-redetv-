"""Chave de idempotência do `POST /v1/jobs` (E7, #274).

O cliente manda `Idempotency-Key` (um UUID por intenção de envio, o mesmo nas repetições).
A primeira chamada reserva a chave, com o id do Job já escolhido; as repetições acham a
reserva e devolvem o mesmo Job. A reserva é por quem chama (sistema ou pessoa), então dois
sistemas com a mesma chave têm Jobs diferentes, e uma chave reusada com outro corpo é erro.
A reserva vem antes da gravação do Job: se o processo morre entre as duas, a repetição acha
a reserva sem Job e o grava com o mesmo id. Depois de gravar, a reserva é marcada: repetição
de Job na lixeira ou purgado (reserva marcada, sem Job) responde 410.
"""

import hashlib
import json
import threading
from datetime import datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

# Quanto a reserva vale. O Firestore apaga o documento depois do `expira_em` (política de TTL).
VALIDADE = timedelta(hours=48)
TAMANHO_MAXIMO_DA_CHAVE = 255


class Reserva(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    # SHA-256 do corpo do pedido: o mesmo corpo é repetição, outro corpo é conflito.
    impressao: str
    criada_em: datetime
    expira_em: datetime
    # Marcada depois de gravar o Job: reserva marcada sem Job é Job purgado (410); sem
    # marca e sem Job é queda antes de gravar (a repetição o recria).
    job_gravado: bool = False


class ChaveReusadaComOutroCorpo(Exception):
    """A mesma chave de idempotência chegou com um corpo diferente (409)."""


class RepositorioDeIdempotencia(Protocol):
    def reservar(
        self, escopo: str, chave: str, impressao: str, job_id: str, agora: datetime
    ) -> tuple[Reserva, bool]:
        """Reserva a chave para o `job_id`, de forma atômica: de duas chamadas
        simultâneas com a mesma chave, só uma cria. Devolve a reserva que vale e se foi
        esta chamada que a criou. Reserva vencida conta como inexistente. Levanta
        `ChaveReusadaComOutroCorpo` se a reserva existente tem outra impressão."""
        ...

    def marcar_job_gravado(self, escopo: str, chave: str) -> None:
        """Marca a reserva como com o Job gravado. Sem reserva, não faz nada."""
        ...


def impressao_do_corpo(corpo: dict[str, Any]) -> str:
    texto = json.dumps(corpo, separators=(",", ":"), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(texto.encode()).hexdigest()


def id_da_reserva(escopo: str, chave: str) -> str:
    """Id do documento: o hash esconde o texto da chave (que o cliente escolhe) e cabe
    em qualquer id do Firestore."""
    return hashlib.sha256(f"{escopo}\0{chave}".encode()).hexdigest()


def nova_reserva(impressao: str, job_id: str, agora: datetime) -> Reserva:
    return Reserva(
        job_id=job_id,
        impressao=impressao,
        criada_em=agora,
        expira_em=agora + VALIDADE,
    )


def conferir(reserva: Reserva, impressao: str) -> None:
    if reserva.impressao != impressao:
        raise ChaveReusadaComOutroCorpo


class RepositorioDeIdempotenciaEmMemoria:
    def __init__(self) -> None:
        self._reservas: dict[str, Reserva] = {}
        self._trava = threading.Lock()

    def reservar(
        self, escopo: str, chave: str, impressao: str, job_id: str, agora: datetime
    ) -> tuple[Reserva, bool]:
        id_ = id_da_reserva(escopo, chave)
        with self._trava:
            existente = self._reservas.get(id_)
            if existente is not None and existente.expira_em > agora:
                conferir(existente, impressao)
                return existente, False
            criada = nova_reserva(impressao, job_id, agora)
            self._reservas[id_] = criada
            return criada, True

    def marcar_job_gravado(self, escopo: str, chave: str) -> None:
        id_ = id_da_reserva(escopo, chave)
        with self._trava:
            existente = self._reservas.get(id_)
            if existente is not None:
                self._reservas[id_] = existente.model_copy(update={"job_gravado": True})
