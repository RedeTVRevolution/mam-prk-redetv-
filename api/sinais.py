"""Sinais de qualidade que saem no log, uma linha JSON por evento, para os alertas (#286).

O Cloud Run lê a linha JSON do stdout como `jsonPayload`, com `severity`. Os campos
`evento`, `etapa` e os percentuais são o contrato com as métricas de log do
`infra/main.tf`: mudar um nome aqui pede mudar o filtro lá.
"""

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from api.decupagem import Decupagem
from api.identidade import nao_identificado

Registrar = Callable[[str], None]


def imprimir(linha: str) -> None:
    print(linha, flush=True)


@dataclass
class ContagemDaAnalise:
    """O que a análise por janelas viu e a Decupagem final não mostra. As janelas rodam
    em threads: as contagens passam pelo trinco."""

    janelas: int = 0
    escalonadas: int = 0
    fora_do_esquema: int = 0
    _trinco: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def resposta_fora_do_esquema(self) -> None:
        with self._trinco:
            self.fora_do_esquema += 1


def _percentual(parte: int, total: int) -> float:
    return round(100 * parte / total, 1) if total else 0.0


def registro_do_video_concluido(
    job_id: str,
    programa: str | None,
    decupagem: Decupagem,
    contagem: ContagemDaAnalise,
) -> str:
    """Pessoas "na imagem" são as que têm alguma aparição; "não identificadas", as que o
    modelo deixou sem nome (a identificação do #112 ainda não rodou neste ponto)."""
    na_imagem = [p for p in decupagem.pessoas if p.na_imagem]
    sem_nome = [p for p in na_imagem if nao_identificado(p.nome)]
    return json.dumps(
        {
            "severity": "INFO",
            "evento": "video_concluido",
            "job_id": job_id,
            "programa": programa or "",
            "janelas": contagem.janelas,
            "janelas_escalonadas": contagem.escalonadas,
            "pct_escalonadas": _percentual(contagem.escalonadas, contagem.janelas),
            "pessoas_na_imagem": len(na_imagem),
            "pessoas_nao_identificadas": len(sem_nome),
            "pct_nao_identificadas": _percentual(len(sem_nome), len(na_imagem)),
            "respostas_fora_do_esquema": contagem.fora_do_esquema,
        },
        ensure_ascii=False,
    )


def registro_da_falha_de_etapa(etapa: str, job_id: str, motivo: str) -> str:
    return json.dumps(
        {
            "severity": "WARNING",
            "evento": "falha_de_etapa",
            "etapa": etapa,
            "job_id": job_id,
            "motivo": motivo,
        },
        ensure_ascii=False,
    )
