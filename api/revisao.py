"""Tempo de revisão (#251): quanto a pessoa trabalhou em cada vídeo na tela de catalogação.

A tela avisa a API (`pulso`) ao começar, a cada minuto com atividade e ao sair. O tempo ativo
de cada (vídeo, pessoa) cresce pela fronteira do que já foi contado (`ultimo_pulso`): um pulso
dentro do limite soma o que passou desde a fronteira, um intervalo maior abre outra sessão e
não conta, e um pulso que não passa da fronteira (outra aba da mesma pessoa) não soma de novo.
Um `inicio` logo depois de um `fim` (a pessoa saiu e voltou) também abre outra sessão.
"""

import csv
import io
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import AwareDatetime, BaseModel

from api.auth import ChamadorAutenticado, Usuario
from api.jobs import (
    RepositorioDeJobs,
    _confere_permissao,
    _exige_editar,
    _tem_permissao,
)

LIMITE_DE_INATIVIDADE_S = 300.0

Evento = Literal["inicio", "atividade", "fim"]


class Pulso(BaseModel):
    job_id: str
    uid: str
    email: str
    quando: AwareDatetime
    evento: Evento
    duracao_s: float | None = None


class Medida(BaseModel):
    """O que se sabe de uma pessoa num vídeo."""

    job_id: str
    uid: str
    email: str
    ativo_s: float = 0.0
    sessoes: int = 0
    duracao_s: float | None = None
    ultimo_pulso: AwareDatetime
    ultimo_evento: Evento | None = None


def aplicar(medida: Medida | None, pulso: Pulso, limite_s: float) -> Medida:
    """A medida depois do pulso. Pura: quem chama grava (de forma atômica)."""
    duracao = pulso.duracao_s
    if medida is None:
        return Medida(
            job_id=pulso.job_id,
            uid=pulso.uid,
            email=pulso.email,
            sessoes=1,
            duracao_s=duracao,
            ultimo_pulso=pulso.quando,
            ultimo_evento=pulso.evento,
        )
    intervalo = (pulso.quando - medida.ultimo_pulso).total_seconds()
    ativo, sessoes = medida.ativo_s, medida.sessoes
    voltou = pulso.evento == "inicio" and medida.ultimo_evento == "fim"
    if intervalo > limite_s or voltou:
        sessoes += 1
    elif intervalo > 0 and pulso.evento != "inicio":
        ativo += intervalo
    return medida.model_copy(
        update={
            "ativo_s": ativo,
            "sessoes": sessoes,
            "duracao_s": duracao if duracao is not None else medida.duracao_s,
            "email": pulso.email,
            "ultimo_pulso": max(medida.ultimo_pulso, pulso.quando),
            "ultimo_evento": pulso.evento,
        }
    )


class RepositorioDeRevisao(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def aplicar(self, pulso: Pulso, limite_s: float) -> Medida:
        """Lê a medida de (vídeo, pessoa), aplica o pulso e grava, tudo atômico."""
        ...

    def do_video(self, job_id: str) -> list[Medida]: ...

    def todas(self, desde: datetime | None = None) -> list[Medida]:
        """As medidas cujo último pulso é de `desde` em diante."""
        ...


class RepositorioDeRevisaoEmMemoria:
    def __init__(self) -> None:
        self._medidas: dict[tuple[str, str], Medida] = {}

    def aplicar(self, pulso: Pulso, limite_s: float) -> Medida:
        chave = (pulso.job_id, pulso.uid)
        medida = aplicar(self._medidas.get(chave), pulso, limite_s)
        self._medidas[chave] = medida
        return medida

    def do_video(self, job_id: str) -> list[Medida]:
        return sorted(
            (m for m in self._medidas.values() if m.job_id == job_id),
            key=lambda m: m.email,
        )

    def todas(self, desde: datetime | None = None) -> list[Medida]:
        return sorted(
            (
                m
                for m in self._medidas.values()
                if desde is None or m.ultimo_pulso >= desde
            ),
            key=lambda m: (m.job_id, m.email),
        )


def minutos(ativo_s: float) -> float:
    return round(ativo_s / 60, 2)


def minutos_por_hora_de_video(ativo_s: float, duracao_s: float | None) -> float | None:
    """Minutos de revisão por hora de vídeo; `None` se o vídeo não tem duração."""
    if not duracao_s:
        return None
    return round(ativo_s / 60 / (duracao_s / 3600), 2)


class CorpoDoPulso(BaseModel):
    evento: Evento


class PessoaNaRevisao(BaseModel):
    uid: str
    email: str
    ativo_s: float
    minutos: float
    sessoes: int
    minutos_por_hora_de_video: float | None


class RevisaoDoVideo(BaseModel):
    job_id: str
    duracao_s: float | None
    pessoas: list[PessoaNaRevisao]
    total_ativo_s: float
    minutos_por_hora_de_video: float | None


def _linha_da_pessoa(medida: Medida, duracao_s: float | None) -> PessoaNaRevisao:
    return PessoaNaRevisao(
        uid=medida.uid,
        email=medida.email,
        ativo_s=medida.ativo_s,
        minutos=minutos(medida.ativo_s),
        sessoes=medida.sessoes,
        minutos_por_hora_de_video=minutos_por_hora_de_video(medida.ativo_s, duracao_s),
    )


def _exige_ver_a_revisao(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: pessoa com `correcao.aprovar` ou `auditoria.ver`; sistema não consulta."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não consulta o tempo de revisão")
    if not _tem_permissao(request, chamador, "correcao.aprovar"):
        _confere_permissao(request, chamador, "auditoria.ver")
    return chamador


def criar_rotas_da_revisao(
    jobs: RepositorioDeJobs,
    revisao: RepositorioDeRevisao,
    relogio: Callable[[], datetime],
    limite_s: float = LIMITE_DE_INATIVIDADE_S,
) -> APIRouter:
    rotas = APIRouter(prefix="/jobs")

    @rotas.post("/{job_id}/revisao/pulso", status_code=204)
    def pulso(
        job_id: str,
        corpo: CorpoDoPulso,
        pessoa: Annotated[Usuario, Depends(_exige_editar)],
    ) -> Response:
        job = jobs.obter(job_id)
        if job is None:
            raise HTTPException(404, "Job não encontrado")
        revisao.aplicar(
            Pulso(
                job_id=job.id,
                uid=pessoa.uid,
                email=pessoa.email,
                quando=relogio(),
                evento=corpo.evento,
                duracao_s=job.duracao_s,
            ),
            limite_s,
        )
        return Response(status_code=204)

    @rotas.get("/{job_id}/revisao")
    def total(
        job_id: str,
        _pessoa: Annotated[Usuario, Depends(_exige_ver_a_revisao)],
    ) -> RevisaoDoVideo:
        job = jobs.obter(job_id)
        if job is None:
            raise HTTPException(404, "Job não encontrado")
        medidas = revisao.do_video(job.id)
        ativo = sum(m.ativo_s for m in medidas)
        return RevisaoDoVideo(
            job_id=job.id,
            duracao_s=job.duracao_s,
            pessoas=[_linha_da_pessoa(m, job.duracao_s) for m in medidas],
            total_ativo_s=ativo,
            minutos_por_hora_de_video=minutos_por_hora_de_video(ativo, job.duracao_s),
        )

    return rotas


COLUNAS_DO_CSV = (
    "job_id",
    "pessoa",
    "uid",
    "minutos",
    "sessoes",
    "duracao_do_video_min",
    "minutos_por_hora_de_video",
)


def relatorio_em_csv(medidas: list[Medida]) -> str:
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(COLUNAS_DO_CSV)
    for m in medidas:
        por_hora = minutos_por_hora_de_video(m.ativo_s, m.duracao_s)
        escritor.writerow(
            [
                m.job_id,
                m.email,
                m.uid,
                minutos(m.ativo_s),
                m.sessoes,
                "" if m.duracao_s is None else round(m.duracao_s / 60, 2),
                "" if por_hora is None else por_hora,
            ]
        )
    return saida.getvalue()
