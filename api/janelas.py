"""Plano de janelas de análise: divide a duração do vídeo em núcleos de 300 s.

Cada janela decupa o seu núcleo e vê 10 s de contexto de cada lado, limitado
ao vídeo. Tudo em milissegundos inteiros.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

DURACAO_DA_JANELA_MS = 300_000
CONTEXTO_MS = 10_000
# ponytail: 3 tentativas por janela é um palpite; o valor sai do piloto.
LIMITE_DE_TENTATIVAS = 3

Situacao = Literal["pendente", "em_andamento", "concluida", "falhou"]


@dataclass(frozen=True)
class Janela:
    indice: int
    inicio_ms: int
    fim_ms: int
    inicio_contexto_ms: int
    fim_contexto_ms: int


def planejar_janelas(duracao_ms: int) -> list[Janela]:
    """Núcleos contíguos de 300 s que cobrem o vídeo; o último pode ser mais curto.

    Duração zero não tem o que decupar e devolve lista vazia; duração negativa
    é erro de quem chamou.
    """
    if duracao_ms < 0:
        raise ValueError(f"duração negativa: {duracao_ms} ms")
    janelas = []
    for indice, inicio in enumerate(range(0, duracao_ms, DURACAO_DA_JANELA_MS)):
        fim = min(inicio + DURACAO_DA_JANELA_MS, duracao_ms)
        janelas.append(
            Janela(
                indice=indice,
                inicio_ms=inicio,
                fim_ms=fim,
                inicio_contexto_ms=max(inicio - CONTEXTO_MS, 0),
                fim_contexto_ms=min(fim + CONTEXTO_MS, duracao_ms),
            )
        )
    return janelas


@dataclass(frozen=True)
class EstadoJanela:
    indice: int
    situacao: Situacao
    tentativas: int
    erro: str | None


@dataclass(frozen=True)
class Falha:
    indice: int
    erro: str | None


@dataclass(frozen=True)
class SituacaoDoJob:
    prontas: int
    total: int
    falha: Falha | None
    pode_consolidar: bool


def _terminal(estado: EstadoJanela) -> bool:
    return estado.situacao in ("concluida", "falhou")


def iniciar(estado: EstadoJanela, limite: int = LIMITE_DE_TENTATIVAS) -> EstadoJanela:
    """Começa uma tentativa. Reiniciar uma janela em andamento (o serviço caiu)
    também conta; se isso já esgotou o limite, a janela falha."""
    if _terminal(estado):
        return estado
    if estado.situacao == "em_andamento" and estado.tentativas >= limite:
        return replace(estado, situacao="falhou", erro="limite de tentativas esgotado")
    return replace(estado, situacao="em_andamento", tentativas=estado.tentativas + 1)


def concluir(estado: EstadoJanela) -> EstadoJanela:
    if _terminal(estado):
        return estado
    return replace(estado, situacao="concluida")


def falhar(
    estado: EstadoJanela, erro: str, limite: int = LIMITE_DE_TENTATIVAS
) -> EstadoJanela:
    """Volta a pendente se ainda há tentativas; senão vai a falhou com o erro."""
    if _terminal(estado):
        return estado
    situacao: Situacao = "falhou" if estado.tentativas >= limite else "pendente"
    return replace(estado, situacao=situacao, erro=erro)


def situacao_do_job(estados: Sequence[EstadoJanela]) -> SituacaoDoJob:
    """Progresso do job. Uma janela falha derruba o job: nunca há decupagem parcial."""
    falha = next(
        (Falha(e.indice, e.erro) for e in estados if e.situacao == "falhou"), None
    )
    prontas = sum(e.situacao == "concluida" for e in estados)
    return SituacaoDoJob(
        prontas=prontas,
        total=len(estados),
        falha=falha,
        pode_consolidar=bool(estados) and prontas == len(estados),
    )
