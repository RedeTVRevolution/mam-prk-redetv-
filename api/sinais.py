"""Sinais de qualidade que saem no log, uma linha JSON por evento, para os alertas (#286).

O Cloud Run lê a linha JSON do stdout como `jsonPayload`, com `severity`. Os campos
`evento`, `etapa` e os percentuais são o contrato com as métricas de log do
`infra/modulos/mam/main.tf`: mudar um nome aqui pede mudar o filtro lá.

A falha de etapa sai uma vez por falha: daqui, quando o próprio Job a trata e termina sem
erro (a análise que derruba o Job, a identificação incompleta); do Workflows
(`marca_fim`), quando a execução do Job falha (erro, tempo esgotado, memória estourada).
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


def registro_da_resposta_fora_do_esquema(modelo: str, motivo: str) -> str:
    """Uma linha por resposta recusada, de qualquer chamada ao modelo: a métrica conta as linhas."""
    return json.dumps(
        {
            "severity": "WARNING",
            "evento": "resposta_fora_do_esquema",
            "modelo": modelo,
            "motivo": motivo[:300],
        },
        ensure_ascii=False,
    )


def registro_do_erro_http(
    status: int, codigo: str, mensagem: str, modelo: str, etapa: str | None = None
) -> str:
    """Uma linha por resposta de erro do Vertex (#617): o que o serviço disse, com a mensagem
    limitada. Nunca o pedido, a credencial nem o vídeo."""
    registro: dict[str, object] = {
        "severity": "ERROR" if status < 500 and status != 429 else "WARNING",
        "evento": "erro_http_do_modelo",
        "status": status,
        "codigo": codigo,
        "mensagem": mensagem[:300],
        "modelo": modelo,
    }
    if etapa:
        registro["etapa"] = etapa
    return json.dumps(registro, ensure_ascii=False)


def registro_das_pessoas_fora_da_pauta(pautas: dict[str, list[str]]) -> str:
    """Uma linha por resposta corrigida: os ids que o modelo citou na pauta sem declará-los
    em `pessoas` e que saíram dela (pauta -> ids). Evento próprio: não conta no alerta."""
    return json.dumps(
        {
            "severity": "WARNING",
            "evento": "pessoas_fora_da_pauta_removidas",
            "pautas": pautas,
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


def registro_do_uso_do_modelo(
    modelo: str,
    entrada: int,
    resposta: int,
    raciocinio: int = 0,
    entrada_em_cache: int = 0,
    modo: str = "",
    etapa: str | None = None,
) -> str:
    """Uma linha por chamada ao modelo: a etapa é o Job que a escreve (`resource.labels.job_name`),
    e o custo dos painéis é a soma dos tokens vezes o preço do modelo (#288).

    `tokens_de_saida` segue sendo resposta + raciocínio (o que o painel lê); os campos
    separados deixam medir o raciocínio, o cache e o modo (`trafficType`, `ON_DEMAND_FLEX`
    no Flex). Fora de um Job (a busca, na API) a etapa vai no próprio registro."""
    registro: dict[str, object] = {
        "severity": "INFO",
        "evento": "uso_do_modelo",
        "modelo": modelo,
        "tokens_de_entrada": entrada,
        "tokens_de_saida": resposta + raciocinio,
        "tokens_de_resposta": resposta,
        "tokens_de_raciocinio": raciocinio,
        "tokens_de_entrada_em_cache": entrada_em_cache,
        "modo": modo,
    }
    if etapa is not None:
        registro["etapa"] = etapa
    return json.dumps(registro, ensure_ascii=False)
