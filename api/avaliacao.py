"""Avaliação diária por rubrica (#255): a amostra, as rubricas, o juiz e a regra de queda.

Uma fração dos vídeos concluídos no dia (ao menos um por programa) é sorteada de forma
reproduzível; para cada requisito (`api/rubricas.toml`) o serviço de avaliação da Vertex
(`evaluateInstances`, métrica ponto a ponto) dá uma nota de 1 a 5 sobre a Decupagem, que vira
0 a 100. A API só recebe texto: os quadros-chave entram pelas descrições dos planos e pelos
caminhos dos JPEGs que a Decupagem já guarda; mandar as imagens ao juiz fica para quando o
serviço aceitar. O que o Job grava e como a queda é detectada: `api/avaliacao_job.py`.
"""

import hashlib
import json
import math
import tomllib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from api.decupagem import Decupagem
from api.gemini import ErroHttp, SessaoHttp
from api.jobs import Job

REQUISITOS = ("famosos", "mencoes", "pautas", "broll", "comerciais")
ARQUIVO_DAS_RUBRICAS = Path(__file__).parent / "rubricas.toml"
NOTA_MINIMA = 1
NOTA_MAXIMA = 5


class Rubrica(BaseModel):
    requisito: str
    campos: list[str]
    criterios: list[str]


class Nota(BaseModel):
    """`nota` de 0 a 100; `explicacao` é a do juiz."""

    nota: float
    explicacao: str = ""


class Avaliacao(BaseModel):
    """As notas de um vídeo num dia, com a versão do pipeline que produziu a Decupagem."""

    dia: date
    job_id: str
    programa: str | None
    versao_pipeline: str | None
    notas: dict[str, Nota]
    caracteres: int
    avaliado_em: datetime


class Queda(BaseModel):
    requisito: str
    media: float
    motivo: Literal["abaixo_do_limiar", "queda_na_semana"]
    limiar: float
    media_anterior: float | None = None


class Avaliador(Protocol):
    def avaliar(self, rubrica: Rubrica, conteudo: str) -> Nota: ...


class AvaliacaoFalhou(Exception):
    pass


def ler_rubricas(arquivo: Path = ARQUIVO_DAS_RUBRICAS) -> dict[str, Rubrica]:
    dados = tomllib.loads(arquivo.read_text())
    faltam = set(REQUISITOS) - dados.keys()
    if faltam:
        raise ValueError(f"rubricas sem requisito: {sorted(faltam)}")
    return {nome: Rubrica(requisito=nome, **dados[nome]) for nome in REQUISITOS}


def _ordem(semente: str, dia: date, job_id: str) -> str:
    return hashlib.sha256(f"{semente}:{dia.isoformat()}:{job_id}".encode()).hexdigest()


def amostrar(jobs: Iterable[Job], dia: date, fracao: float, semente: str) -> list[Job]:
    """Por programa, `ceil(fracao * n)` vídeos (ao menos um), na ordem do hash do sorteio.

    O sorteio depende só da semente, do dia e do id: o mesmo dia dá a mesma amostra, mesmo
    que o Job rode de novo. Vídeo sem programa forma um grupo só dele."""
    if not 0 <= fracao <= 1:
        raise ValueError("a fração da amostra vai de 0 a 1")
    grupos: dict[str | None, list[Job]] = defaultdict(list)
    for job in jobs:
        grupos[job.programa].append(job)
    escolhidos: list[Job] = []
    for grupo in grupos.values():
        grupo.sort(key=lambda j: _ordem(semente, dia, j.id))
        escolhidos += grupo[: max(1, math.ceil(fracao * len(grupo)))]
    return sorted(escolhidos, key=lambda j: j.id)


def conteudo_do(rubrica: Rubrica, decupagem: Decupagem) -> str:
    """O JSON dos campos da Decupagem que a rubrica avalia."""
    todos = decupagem.model_dump(mode="json")
    return json.dumps(
        {campo: todos.get(campo) for campo in rubrica.campos}, ensure_ascii=False
    )


def prompt_da_rubrica(rubrica: Rubrica) -> str:
    criterios = "\n".join(f"- {c}" for c in rubrica.criterios)
    return (
        "Você avalia a decupagem automática de um vídeo de TV (JSON). Avalie só o "
        f"requisito '{rubrica.requisito}', pelos critérios:\n{criterios}\n\n"
        f"Dê {NOTA_MINIMA} (nenhum critério cumprido) a {NOTA_MAXIMA} (todos cumpridos) "
        "e explique em uma frase.\n\nDecupagem:\n{conteudo}"
    )


def em_pontos(nota_do_juiz: float) -> float:
    """A nota de 1 a 5 do juiz em 0 a 100."""
    limitada = min(max(nota_do_juiz, NOTA_MINIMA), NOTA_MAXIMA)
    return (limitada - NOTA_MINIMA) / (NOTA_MAXIMA - NOTA_MINIMA) * 100


class AvaliadorVertex:
    """`evaluateInstances` com uma métrica ponto a ponto escrita na hora, pela rubrica."""

    def __init__(
        self, projeto: str, regiao: str, modelo_juiz: str, sessao: SessaoHttp
    ) -> None:
        self._projeto = projeto
        self._regiao = regiao
        self._modelo = modelo_juiz
        self._sessao = sessao

    def avaliar(self, rubrica: Rubrica, conteudo: str) -> Nota:
        base = f"projects/{self._projeto}/locations/{self._regiao}"
        url = f"https://{self._regiao}-aiplatform.googleapis.com/v1/{base}:evaluateInstances"
        corpo = {
            "pointwiseMetricInput": {
                "metricSpec": {"metricPromptTemplate": prompt_da_rubrica(rubrica)},
                "instance": {"jsonInstance": json.dumps({"conteudo": conteudo})},
            },
            "autoraterConfig": {
                "autoraterModel": f"{base}/publishers/google/models/{self._modelo}"
            },
        }
        try:
            resposta = self._sessao.post(url, json=corpo, timeout=120)
        except Exception as e:  # queda de conexão e timeout
            raise AvaliacaoFalhou(str(e)) from e
        if resposta.status_code != 200:
            raise AvaliacaoFalhou(str(ErroHttp(resposta.status_code)))
        try:
            resultado = resposta.json()["pointwiseMetricResult"]
            nota = float(resultado["score"])
            explicacao = str(resultado.get("explanation", ""))
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            raise AvaliacaoFalhou(f"o juiz não devolveu nota: {e!r}") from e
        if math.isnan(nota):
            raise AvaliacaoFalhou("o juiz não devolveu nota: NaN")
        return Nota(nota=em_pontos(nota), explicacao=explicacao)


def medias(avaliacoes: Iterable[Avaliacao]) -> dict[str, float]:
    """A média de cada requisito sobre os vídeos que o têm."""
    notas: dict[str, list[float]] = defaultdict(list)
    for a in avaliacoes:
        for requisito, nota in a.notas.items():
            notas[requisito].append(nota.nota)
    return {r: sum(v) / len(v) for r, v in notas.items()}


def detectar_quedas(
    hoje: Iterable[Avaliacao],
    anteriores: Iterable[Avaliacao],
    limiar: float,
    queda_maxima: float,
) -> list[Queda]:
    """Requisito cuja média de hoje está abaixo do limiar, ou caiu mais que `queda_maxima`
    pontos da média dos dias anteriores. Sem dados de antes, só vale o limiar."""
    de_hoje = medias(hoje)
    de_antes = medias(anteriores)
    quedas: list[Queda] = []
    for requisito in REQUISITOS:
        if requisito not in de_hoje:
            continue
        media = de_hoje[requisito]
        antes = de_antes.get(requisito)
        motivo: Literal["abaixo_do_limiar", "queda_na_semana"]
        if media < limiar:
            motivo = "abaixo_do_limiar"
        elif antes is not None and antes - media > queda_maxima:
            motivo = "queda_na_semana"
        else:
            continue
        quedas.append(
            Queda(
                requisito=requisito,
                media=media,
                motivo=motivo,
                limiar=limiar,
                media_anterior=antes,
            )
        )
    return quedas


def registro_da_queda(queda: Queda, dia: date, extra: Mapping[str, Any]) -> str:
    """A linha de log que o alerta do #286 pega: `evento` e `severity` fixos."""
    return json.dumps(
        {
            "severity": "WARNING",
            "evento": "queda_de_qualidade",
            "dia": dia.isoformat(),
            **queda.model_dump(),
            **extra,
        },
        ensure_ascii=False,
    )
