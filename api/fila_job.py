"""Cloud Run Job que amostra a fila de processamento no log, de 5 em 5 minutos (#288).

O Cloud Scheduler o dispara; ele conta os Jobs ainda em andamento por estado e a idade do
mais antigo (desde a criação) e loga uma linha JSON por estado (`evento: fila_de_jobs`),
inclusive o estado vazio, para o painel mostrar a fila zerada em vez de um buraco. As
métricas de log do `infra/modulos/mam/main.tf` leem `estado`, `quantidade` e `idade_do_mais_antigo_s`:
mudar um nome aqui pede mudar lá. Os Jobs terminados (concluído, falhou, cancelado) ficam
de fora: a falha já tem o alerta de falha de etapa.

Ambiente: `GCP_PROJECT_ID`.
"""

import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from typing import get_args

from google.cloud import firestore

from api.comparar_objetos import FaltaNoAmbiente, exigir_do_ambiente
from api.jobs import Estado, FiltroDeJobs, RepositorioDeJobs, agora_utc
from api.nuvem import RepositorioFirestore
from api.sinais import Registrar, imprimir

ESTADOS_DA_FILA: tuple[Estado, ...] = ("aguardando_upload", "validando", "analisando")
ESTADOS_QUE_TERMINARAM: frozenset[str] = frozenset({"concluido", "falhou", "cancelado"})
assert set(ESTADOS_DA_FILA) | ESTADOS_QUE_TERMINARAM == set(get_args(Estado))


def amostrar_a_fila(
    repositorio: RepositorioDeJobs, agora: datetime, registrar: Registrar = imprimir
) -> None:
    na_fila = repositorio.consultar(
        FiltroDeJobs(estados=frozenset(ESTADOS_DA_FILA))
    ).jobs
    for estado in ESTADOS_DA_FILA:
        do_estado = [j for j in na_fila if j.estado == estado]
        idade = max((agora - j.criado_em for j in do_estado), default=None)
        registrar(
            json.dumps(
                {
                    "severity": "INFO",
                    "evento": "fila_de_jobs",
                    "estado": estado,
                    "quantidade": len(do_estado),
                    "idade_do_mais_antigo_s": round(idade.total_seconds())
                    if idade
                    else 0,
                }
            )
        )


def main(ambiente: Mapping[str, str] = os.environ) -> int:
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    amostrar_a_fila(
        RepositorioFirestore(firestore.Client(project=projeto)), agora_utc()
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
