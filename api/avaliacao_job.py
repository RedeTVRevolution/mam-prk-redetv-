"""Cloud Run Job da avaliação diária por rubrica (#255), disparado pelo Cloud Scheduler.

Sorteia a amostra dos vídeos concluídos no dia (`DIA`, padrão: hoje em UTC), avalia cada
requisito de cada vídeo e grava as notas por vídeo, requisito e `versao_pipeline`. Depois
compara a média do dia de cada requisito com o limiar e com a média dos `JANELA_DIAS` dias
anteriores, e loga um registro estruturado por queda (`evento: queda_de_qualidade`). Rodar de
novo no mesmo dia não reavalia o que já tem nota. Falha do juiz num requisito deixa só ele
de fora (com aviso); o Job termina bem.

Ambiente: `GCP_PROJECT_ID`, `REGIAO_DA_AVALIACAO`, `MODELO_DO_JUIZ`, `BUCKET_ACEITOS`,
`BUCKET_DECUPAGENS`; opcionais `FRACAO_DA_AVALIACAO`, `SEMENTE_DA_AVALIACAO`,
`LIMIAR_DA_AVALIACAO`, `QUEDA_MAXIMA_DA_AVALIACAO`, `JANELA_DA_AVALIACAO_DIAS` e
`PRECO_POR_MIL_CARACTERES` (para o custo estimado do dia, no log).
"""

import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, cast

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.avaliacao import (
    REQUISITOS,
    Avaliacao,
    AvaliacaoFalhou,
    Avaliador,
    AvaliadorVertex,
    Rubrica,
    amostrar,
    conteudo_do,
    detectar_quedas,
    ler_rubricas,
    registro_da_queda,
)
from api.comparar_objetos import FaltaNoAmbiente, exigir_do_ambiente
from api.decupagem import Decupagem
from api.gemini import SessaoHttp
from api.jobs import FiltroDeJobs, Job, RepositorioDeJobs
from api.nuvem import (
    DecupagensStorage,
    RepositorioDeAvaliacoesFirestore,
    RepositorioFirestore,
)

FRACAO_PADRAO = 0.1
LIMIAR_PADRAO = 60.0
QUEDA_MAXIMA_PADRAO = 10.0
JANELA_PADRAO_DIAS = 7


class RepositorioDeAvaliacoes(Protocol):
    def gravar(self, avaliacao: Avaliacao) -> None: ...

    def do_dia(self, dia: date) -> list[Avaliacao]: ...

    def entre(self, de: date, ate: date) -> list[Avaliacao]:
        """Os dias de `de` a `ate`, inclusive."""
        ...


class AvaliacoesEmMemoria:
    def __init__(self) -> None:
        self._por_chave: dict[tuple[date, str], Avaliacao] = {}

    def gravar(self, avaliacao: Avaliacao) -> None:
        self._por_chave[(avaliacao.dia, avaliacao.job_id)] = avaliacao

    def do_dia(self, dia: date) -> list[Avaliacao]:
        return self.entre(dia, dia)

    def entre(self, de: date, ate: date) -> list[Avaliacao]:
        return [a for a in self._por_chave.values() if de <= a.dia <= ate]


class DecupagensDaAvaliacao(Protocol):
    def ler_decupagem(self, job_id: str) -> Decupagem | None: ...


def concluidos_no_dia(repositorio: RepositorioDeJobs, dia: date) -> list[Job]:
    """Os Jobs `concluido` cuja última atualização caiu em `dia` (UTC)."""
    pagina = repositorio.consultar(FiltroDeJobs(estados=frozenset({"concluido"})))
    return [j for j in pagina.jobs if j.atualizado_em.astimezone(UTC).date() == dia]


def _avaliar_video(
    job: Job,
    decupagem: Decupagem,
    rubricas: Mapping[str, Rubrica],
    avaliador: Avaliador,
    dia: date,
    agora: datetime,
    aviso: Callable[[str], None],
) -> Avaliacao | None:
    notas = {}
    caracteres = 0
    for requisito in REQUISITOS:
        conteudo = conteudo_do(rubricas[requisito], decupagem)
        try:
            notas[requisito] = avaliador.avaliar(rubricas[requisito], conteudo)
        except AvaliacaoFalhou as e:
            aviso(f"{job.id}/{requisito}: {e}")
            continue
        caracteres += len(conteudo)
    if not notas:
        return None
    return Avaliacao(
        dia=dia,
        job_id=job.id,
        programa=job.programa,
        versao_pipeline=decupagem.versao_pipeline,
        notas=notas,
        caracteres=caracteres,
        avaliado_em=agora,
    )


def executar(
    dia: date,
    repositorio: RepositorioDeJobs,
    decupagens: DecupagensDaAvaliacao,
    avaliador: Avaliador,
    avaliacoes: RepositorioDeAvaliacoes,
    rubricas: Mapping[str, Rubrica],
    *,
    fracao: float = FRACAO_PADRAO,
    semente: str = "",
    limiar: float = LIMIAR_PADRAO,
    queda_maxima: float = QUEDA_MAXIMA_PADRAO,
    janela_dias: int = JANELA_PADRAO_DIAS,
    preco_por_mil_caracteres: float | None = None,
    agora: Callable[[], datetime] = lambda: datetime.now(UTC),
    registrar: Callable[[str], None] = lambda linha: print(linha, flush=True),
) -> dict[str, Any]:
    """Devolve o resumo (`avaliados`, `quedas`); cada queda também sai por `registrar`."""

    def aviso(mensagem: str) -> None:
        registrar(
            json.dumps(
                {
                    "severity": "WARNING",
                    "evento": "avaliacao_falhou",
                    "detalhe": mensagem,
                }
            )
        )

    ja_avaliados = {a.job_id for a in avaliacoes.do_dia(dia)}
    for job in amostrar(concluidos_no_dia(repositorio, dia), dia, fracao, semente):
        if job.id in ja_avaliados:
            continue
        decupagem = decupagens.ler_decupagem(job.id)
        if decupagem is None:
            aviso(f"{job.id}: sem Decupagem")
            continue
        avaliacao = _avaliar_video(
            job, decupagem, rubricas, avaliador, dia, agora(), aviso
        )
        if avaliacao is not None:
            avaliacoes.gravar(avaliacao)

    de_hoje = avaliacoes.do_dia(dia)
    anteriores = avaliacoes.entre(
        dia - timedelta(days=janela_dias), dia - timedelta(days=1)
    )
    quedas = detectar_quedas(de_hoje, anteriores, limiar, queda_maxima)
    for queda in quedas:
        registrar(registro_da_queda(queda, dia, {"videos": len(de_hoje)}))
    caracteres = sum(a.caracteres for a in de_hoje)
    custo = (
        None
        if preco_por_mil_caracteres is None
        else caracteres / 1000 * preco_por_mil_caracteres
    )
    resumo = {
        "evento": "avaliacao_do_dia",
        "dia": dia.isoformat(),
        "avaliados": len(de_hoje),
        "caracteres": caracteres,
        "custo_estimado_usd": custo,
        "custo_por_video_usd": None
        if custo is None or not de_hoje
        else custo / len(de_hoje),
        "quedas": [q.requisito for q in quedas],
    }
    registrar(json.dumps({"severity": "INFO", **resumo}))
    return resumo


def main(ambiente: Mapping[str, str] = os.environ) -> int:
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        regiao = exigir_do_ambiente(ambiente, "REGIAO_DA_AVALIACAO")
        modelo = exigir_do_ambiente(ambiente, "MODELO_DO_JUIZ")
        aceitos = exigir_do_ambiente(ambiente, "BUCKET_ACEITOS")
        bucket = exigir_do_ambiente(ambiente, "BUCKET_DECUPAGENS")
        dia = (
            date.fromisoformat(ambiente["DIA"])
            if ambiente.get("DIA")
            else datetime.now(UTC).date()
        )
        preco = ambiente.get("PRECO_POR_MIL_CARACTERES")
        parametros: dict[str, Any] = {
            "fracao": float(ambiente.get("FRACAO_DA_AVALIACAO", FRACAO_PADRAO)),
            "semente": ambiente.get("SEMENTE_DA_AVALIACAO", ""),
            "limiar": float(ambiente.get("LIMIAR_DA_AVALIACAO", LIMIAR_PADRAO)),
            "queda_maxima": float(
                ambiente.get("QUEDA_MAXIMA_DA_AVALIACAO", QUEDA_MAXIMA_PADRAO)
            ),
            "janela_dias": int(
                ambiente.get("JANELA_DA_AVALIACAO_DIAS", JANELA_PADRAO_DIAS)
            ),
            "preco_por_mil_caracteres": float(preco) if preco else None,
        }
    except (FaltaNoAmbiente, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = cast(SessaoHttp, AuthorizedSession(credenciais))  # type: ignore[no-untyped-call]
    cliente = firestore.Client(project=projeto)
    executar(
        dia,
        RepositorioFirestore(cliente),
        DecupagensStorage(ClienteStorage(project=projeto), aceitos, bucket),
        AvaliadorVertex(projeto, regiao, modelo, sessao),
        RepositorioDeAvaliacoesFirestore(cliente),
        ler_rubricas(),
        **parametros,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
