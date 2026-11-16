"""A comparação de passadas na produção (#248, #639): a regra, o pareamento por requisito e a rota
da tela lado a lado (`GET /v1/jobs/{id}/passadas/{passada}/comparacao`).

A ferramenta de linha de comando (`make comparar-passadas`) está em
`api/ferramentas/comparar_passadas.py`.
"""

import math
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as CaminhoDaRota
from pydantic import BaseModel

from api.auth import Chamador
from api.decupagem import Decupagem
from api.gemini import MODELO
from api.modelo_do_job import Job, RepositorioDeJobs
from api.pareamento import (
    TIPOS_COM_IDENTIDADE,
    TOLERANCIA_MS,
    Item,
    Pareado,
    itens_do_modelo,
    parear,
)
from api.passadas import FORMA_DO_ID, LeituraDePassadas, Passada
from api.permissoes import JobDoPedido, enxerga, exige_escopo
from api.texto import normalizar

LADO_A = "job"
LADO_B = "passada"
NAO_IDENTIFICADO = "nao identificado"


@dataclass(frozen=True)
class Entrada:
    """Um item de um lado, com o Job de onde veio (a soma de vários Jobs mistura)."""

    job_id: str
    identidade: str
    inicio_ms: int
    fim_ms: int
    detalhe: str | None = None


@dataclass(frozen=True)
class Diferenca:
    a: Entrada
    b: Entrada
    motivos: list[str]  # "nome", "tipo" (ou "plano_limpo") e "tempo"


@dataclass(frozen=True)
class Requisito:
    nome: str
    contagem_a: int
    contagem_b: int
    iguais: int
    so_em_a: list[Entrada]
    so_em_b: list[Entrada]
    diferentes: list[Diferenca]
    # Os pares sem diferença (`motivos` vazio), para a tela lado a lado listar os dois lados.
    pares_iguais: list[Diferenca] = field(default_factory=list)


@dataclass(frozen=True)
class Timecode:
    pares: int
    media_ms: float | None
    p95_ms: int | None
    fora_da_tolerancia: int
    tolerancia_ms: int = TOLERANCIA_MS

    @classmethod
    def de(cls, erros_ms: list[int], pares: int, fora: int) -> "Timecode":
        ordenados = sorted(erros_ms)
        return cls(
            pares=pares,
            media_ms=round(sum(ordenados) / len(ordenados), 1) if ordenados else None,
            p95_ms=ordenados[math.ceil(0.95 * len(ordenados)) - 1]
            if ordenados
            else None,
            fora_da_tolerancia=fora,
        )


@dataclass(frozen=True)
class PrecoUsado:
    modelo: str
    entrada: float  # US$ por milhão de tokens
    saida: float


@dataclass(frozen=True)
class Custo:
    tokens_de_entrada: int
    tokens_de_saida: int
    usd: float
    precos: list[PrecoUsado]


@dataclass(frozen=True)
class Tempo:
    etapas: dict[str, float]
    total_s: float


@dataclass(frozen=True)
class LadoDoResultado:
    custo: Custo | None  # `None`: o Job não guarda os tokens
    tempo: Tempo


@dataclass(frozen=True)
class Resultado:
    duracao_ms: int
    requisitos: dict[str, Requisito]
    erros_ms: list[int]  # início e fim de cada par, para somar vários Jobs
    timecode: Timecode
    pares_fora: int
    a: LadoDoResultado
    b: LadoDoResultado


@dataclass(frozen=True)
class ResultadoDoJob:
    job_id: str
    passada_id: str
    modelo: str
    resultado: Resultado


@dataclass(frozen=True)
class Relatorio:
    gerado_em: datetime
    tabela_de_precos_em: str
    jobs: list[ResultadoDoJob]
    total: Resultado


@dataclass
class _Comparacao:
    requisito: Requisito
    pareados: list[Pareado] = field(default_factory=list)


def _entrada(job_id: str, item: Item, detalhes: Mapping[Item, str]) -> Entrada:
    return Entrada(
        job_id, item.identidade, item.inicio_ms, item.fim_ms, detalhes.get(item)
    )


def _um_para_um(
    pareados: list[Pareado], b: list[Item]
) -> tuple[list[Pareado], list[Item], list[Item]]:
    """O `parear` deixa dois itens de A com o mesmo de B (duas pautas dentro de uma só):
    o primeiro fica com ele e os outros voltam para os sem par. Devolve os pares, os itens de
    A que perderam o par e o que sobrou de B."""
    livres = Counter(
        b
    )  # itens iguais são intercambiáveis; sai a primeira cópia de cada
    pares: list[Pareado] = []
    repetidos: list[Item] = []
    usados: Counter[Item] = Counter()
    for p in pareados:
        if livres[p.modelo] > usados[p.modelo]:
            usados[p.modelo] += 1
            pares.append(p)
        else:
            repetidos.append(p.gabarito)
    sobra_b: list[Item] = []
    for item in b:
        if usados[item]:
            usados[item] -= 1
        else:
            sobra_b.append(item)
    return pares, repetidos, sobra_b


def _comparar_requisito(
    nome: str,
    job_id: str,
    a: list[Item],
    b: list[Item],
    *,
    detalhes_a: Mapping[Item, str] | None = None,
    detalhes_b: Mapping[Item, str] | None = None,
    motivo_do_detalhe: str = "tipo",
    motivo_do_nome: str = "nome",
) -> _Comparacao:
    """Pareia com o `parear` do comparador (mesma identidade, ou só o tempo, nas pautas e
    nos planos), um para um, e, entre o que sobrou dos dois lados, procura o mesmo trecho
    com outro nome. Os pares de nome trocado também entram no timecode."""
    detalhes_a, detalhes_b = detalhes_a or {}, detalhes_b or {}
    pareados, sem_par_a = parear(a, b)
    pareados, repetidos, sem_par_b = _um_para_um(pareados, b)
    sem_par_a += repetidos
    if a and a[0].tipo in TIPOS_COM_IDENTIDADE:
        # Sem identidade para o `parear` olhar, só o trecho em comum conta.
        tipo = a[0].tipo
        so_o_tempo = [replace(i, tipo="pauta") for i in sem_par_a]
        outros = [replace(i, tipo="pauta") for i in sem_par_b]
        renomeados, _ = parear(so_o_tempo, outros)
        renomeados, _, _ = _um_para_um(renomeados, outros)
        for r in renomeados:
            ia = replace(r.gabarito, tipo=tipo)
            ib = replace(r.modelo, tipo=tipo)
            pareados.append(Pareado(ia, ib))
            sem_par_a.remove(ia)
            sem_par_b.remove(ib)
    pares_iguais: list[Diferenca] = []
    diferentes: list[Diferenca] = []
    for p in pareados:
        ia, ib = p.gabarito, p.modelo
        motivos = []
        if normalizar(ia.identidade) != normalizar(ib.identidade):
            motivos.append(motivo_do_nome)
        if detalhes_a.get(ia) != detalhes_b.get(ib):
            motivos.append(motivo_do_detalhe)
        if not p.dentro:
            motivos.append("tempo")
        par = Diferenca(
            _entrada(job_id, ia, detalhes_a), _entrada(job_id, ib, detalhes_b), motivos
        )
        (diferentes if motivos else pares_iguais).append(par)
    return _Comparacao(
        Requisito(
            nome=nome,
            contagem_a=len(a),
            contagem_b=len(b),
            iguais=len(pares_iguais),
            so_em_a=[_entrada(job_id, i, detalhes_a) for i in sem_par_a],
            so_em_b=[_entrada(job_id, i, detalhes_b) for i in sem_par_b],
            diferentes=diferentes,
            pares_iguais=pares_iguais,
        ),
        pareados,
    )


def _famoso(item: Item) -> bool:
    return not normalizar(item.identidade).startswith(NAO_IDENTIFICADO)


def _itens_da_decupagem(
    d: Decupagem,
) -> tuple[dict[str, list[Item]], dict[Item, str], dict[Item, str]]:
    """Os itens por requisito; o detalhe do comercial (tipo) e do plano (limpo ou não)."""
    todos = itens_do_modelo(d)
    por_tipo = {
        t: [i for i in todos if i.tipo == t]
        for t in ("aparicao", "mencao", "pauta", "comercial")
    }
    tipos_dos_comerciais: dict[Item, str] = {
        Item("comercial", c.marca, c.inicio_ms, c.fim_ms): c.tipo for c in d.comerciais
    }
    planos = {
        Item("pauta", p.ambiente, p.inicio_ms, p.fim_ms): (
            "limpo" if p.plano_limpo else "com texto ou fala"
        )
        for p in d.planos
    }
    return (
        {
            "famosos": [i for i in por_tipo["aparicao"] if _famoso(i)],
            "mencoes": por_tipo["mencao"],
            "pautas": por_tipo["pauta"],
            "comerciais": por_tipo["comercial"],
            "broll_descricoes": list(planos),
            "broll_limpos": [i for i, v in planos.items() if v == "limpo"],
        },
        tipos_dos_comerciais,
        planos,
    )


REQUISITOS = (
    "famosos",
    "mencoes",
    "pautas",
    "broll_limpos",
    "broll_descricoes",
    "comerciais",
)
# Os planos limpos são um subconjunto dos planos: fora do timecode, para não contar duas vezes.
REQUISITOS_DO_TIMECODE = tuple(r for r in REQUISITOS if r != "broll_limpos")


def comparar_decupagens(
    job_id: str,
    duracao_ms: int,
    a: Decupagem,
    b: Decupagem,
    lado_a: LadoDoResultado,
    lado_b: LadoDoResultado,
) -> Resultado:
    itens_a, comerciais_a, planos_a = _itens_da_decupagem(a)
    itens_b, comerciais_b, planos_b = _itens_da_decupagem(b)
    comparacoes: dict[str, _Comparacao] = {}
    for nome in REQUISITOS:
        extra: dict[str, Any] = {}
        if nome == "comerciais":
            extra = {"detalhes_a": comerciais_a, "detalhes_b": comerciais_b}
        elif nome == "broll_descricoes":
            extra = {
                "detalhes_a": planos_a,
                "detalhes_b": planos_b,
                "motivo_do_detalhe": "plano_limpo",
                "motivo_do_nome": "descricao",
            }
        elif nome == "broll_limpos":
            extra = {"motivo_do_nome": "descricao"}
        comparacoes[nome] = _comparar_requisito(
            nome, job_id, itens_a[nome], itens_b[nome], **extra
        )
    pareados = [p for n in REQUISITOS_DO_TIMECODE for p in comparacoes[n].pareados]
    erros = [e for p in pareados for e in (p.erro_inicio_ms, p.erro_fim_ms)]
    fora = sum(not p.dentro for p in pareados)
    return Resultado(
        duracao_ms=duracao_ms,
        requisitos={n: c.requisito for n, c in comparacoes.items()},
        erros_ms=erros,
        timecode=Timecode.de(erros, len(pareados), fora),
        pares_fora=fora,
        a=lado_a,
        b=lado_b,
    )


def _somar_requisito(parte: list[Requisito]) -> Requisito:
    return Requisito(
        nome=parte[0].nome,
        contagem_a=sum(r.contagem_a for r in parte),
        contagem_b=sum(r.contagem_b for r in parte),
        iguais=sum(r.iguais for r in parte),
        so_em_a=[e for r in parte for e in r.so_em_a],
        so_em_b=[e for r in parte for e in r.so_em_b],
        diferentes=[d for r in parte for d in r.diferentes],
        pares_iguais=[d for r in parte for d in r.pares_iguais],
    )


def _somar_lado(lados: list[LadoDoResultado]) -> LadoDoResultado:
    etapas: dict[str, float] = {}
    for lado in lados:
        for nome, s in lado.tempo.etapas.items():
            etapas[nome] = round(etapas.get(nome, 0.0) + s, 2)
    custos = [lado.custo for lado in lados]
    # Uma soma com um Job sem tokens enganaria: sem custo no total.
    soma: Custo | None = None
    if all(c is not None for c in custos):
        cheios = [c for c in custos if c is not None]
        soma = Custo(
            tokens_de_entrada=sum(c.tokens_de_entrada for c in cheios),
            tokens_de_saida=sum(c.tokens_de_saida for c in cheios),
            usd=round(sum(c.usd for c in cheios), 6),
            precos=list(dict.fromkeys(p for c in cheios for p in c.precos)),
        )
    return LadoDoResultado(
        custo=soma,
        tempo=Tempo(etapas, round(sum(lado.tempo.total_s for lado in lados), 2)),
    )


def somar(resultados: list[Resultado]) -> Resultado:
    """Soma por requisito, para o relatório do piloto inteiro."""
    erros = [e for r in resultados for e in r.erros_ms]
    pares = sum(r.timecode.pares for r in resultados)
    fora = sum(r.pares_fora for r in resultados)
    return Resultado(
        duracao_ms=sum(r.duracao_ms for r in resultados),
        requisitos={
            n: _somar_requisito([r.requisitos[n] for r in resultados])
            for n in REQUISITOS
        },
        erros_ms=erros,
        timecode=Timecode.de(erros, pares, fora),
        pares_fora=fora,
        a=_somar_lado([r.a for r in resultados]),
        b=_somar_lado([r.b for r in resultados]),
    )


def custo_por_hora(custo: Custo | None, duracao_ms: int) -> float | None:
    if custo is None or duracao_ms <= 0:
        return None
    return round(custo.usd / (duracao_ms / 3_600_000), 4)


def tempo_do_job(job: Job) -> Tempo:
    """Cada etapa que terminou; o total vai do começo da primeira ao fim da última, porque
    a transcrição e a leitura da tela rodam juntas."""
    feitas = {n: e for n, e in job.etapas.items() if e.fim is not None}
    etapas: dict[str, float] = {
        n: round((e.fim - e.inicio).total_seconds(), 2)  # type: ignore[operator]
        for n, e in feitas.items()
    }
    total = 0.0
    if feitas:
        total = (
            max(e.fim for e in feitas.values() if e.fim)
            - min(e.inicio for e in feitas.values())
        ).total_seconds()
    return Tempo(etapas, round(total, 2))


def lado_da_passada(passada: Passada) -> LadoDoResultado:
    c = passada.custo
    return LadoDoResultado(
        custo=Custo(
            c.tokens_de_entrada,
            c.tokens_de_saida,
            c.usd,
            [
                PrecoUsado(
                    passada.modelo,
                    c.preco_por_milhao_de_entrada,
                    c.preco_por_milhao_de_saida,
                )
            ],
        ),
        tempo=Tempo(
            {e.nome: e.segundos for e in passada.etapas},
            round(sum(e.segundos for e in passada.etapas), 2),
        ),
    )


class ItemMarcado(BaseModel):
    identidade: str
    inicio_ms: int
    fim_ms: int
    detalhe: str | None
    marca: str  # "igual", "difere" ou "so_aqui"
    motivos: list[str]


class RequisitoLadoALado(BaseModel):
    nome: str
    a: list[ItemMarcado]
    b: list[ItemMarcado]


class LadoNaTela(BaseModel):
    custo_usd: float | None
    custo_por_hora_usd: float | None
    tempo_total_s: float
    etapas: list[dict[str, Any]]


class ComparacaoNaTela(BaseModel):
    passada_id: str
    modelo: str
    modelo_do_job: str
    duracao_ms: int
    a: LadoNaTela
    b: LadoNaTela
    requisitos: list[RequisitoLadoALado]


def _marcado(e: Entrada, marca: str, motivos: list[str]) -> ItemMarcado:
    return ItemMarcado(
        identidade=e.identidade,
        inicio_ms=e.inicio_ms,
        fim_ms=e.fim_ms,
        detalhe=e.detalhe,
        marca=marca,
        motivos=motivos,
    )


def _lado_na_tela(lado: LadoDoResultado, duracao_ms: int) -> LadoNaTela:
    return LadoNaTela(
        custo_usd=lado.custo.usd if lado.custo else None,
        custo_por_hora_usd=custo_por_hora(lado.custo, duracao_ms),
        tempo_total_s=lado.tempo.total_s,
        etapas=[{"nome": n, "segundos": s} for n, s in lado.tempo.etapas.items()],
    )


def comparacao_na_tela(
    r: Resultado, passada: Passada, modelo_do_job: str = MODELO
) -> ComparacaoNaTela:
    """As mesmas regras do `make comparar-passadas`, itens de cada lado em ordem de tempo."""
    requisitos = []
    for nome in REQUISITOS:
        q = r.requisitos[nome]
        a = [_marcado(p.a, "igual", []) for p in q.pares_iguais]
        a += [_marcado(d.a, "difere", d.motivos) for d in q.diferentes]
        a += [_marcado(e, "so_aqui", []) for e in q.so_em_a]
        b = [_marcado(p.b, "igual", []) for p in q.pares_iguais]
        b += [_marcado(d.b, "difere", d.motivos) for d in q.diferentes]
        b += [_marcado(e, "so_aqui", []) for e in q.so_em_b]
        por_tempo = lambda i: (i.inicio_ms, i.fim_ms)
        requisitos.append(
            RequisitoLadoALado(
                nome=nome, a=sorted(a, key=por_tempo), b=sorted(b, key=por_tempo)
            )
        )
    return ComparacaoNaTela(
        passada_id=passada.id,
        modelo=passada.modelo,
        modelo_do_job=modelo_do_job,
        duracao_ms=r.duracao_ms,
        a=_lado_na_tela(r.a, r.duracao_ms),
        b=_lado_na_tela(r.b, r.duracao_ms),
        requisitos=requisitos,
    )


def criar_rotas_da_comparacao(
    repositorio: RepositorioDeJobs,
    passadas: LeituraDePassadas,
    ler_decupagem: Callable[[str], Decupagem],
) -> APIRouter:
    """Só leitura, com `decupagem.ver` e o Job concluído (409 antes, como o `/decupagem`). O
    Job entra com a decupagem do modelo (sem as correções), como no relatório do #248; o custo
    do Job fica "n/d" (ele não guarda os tokens)."""
    rotas = APIRouter(prefix="/jobs")

    @rotas.get("/{job_id}/passadas/{passada_id}/comparacao")
    def comparacao(
        job_id: str,
        passada_id: Annotated[str, CaminhoDaRota(pattern=FORMA_DO_ID)],
        chamador: Annotated[Chamador, Depends(exige_escopo("ler"))],
        lido: JobDoPedido,
    ) -> ComparacaoNaTela:
        job = enxerga(chamador, lido)
        if job.estado != "concluido" or job.duracao_s is None:
            raise HTTPException(409, f"Job em {job.estado}, não concluido")
        passada = passadas.ler_passada(job.id, passada_id)
        if passada is None:
            raise HTTPException(404, "Passada não encontrada")
        resultado = comparar_decupagens(
            job.id,
            round(job.duracao_s * 1000),
            ler_decupagem(job.id),
            passada.decupagem,
            LadoDoResultado(None, tempo_do_job(job)),
            lado_da_passada(passada),
        )
        return comparacao_na_tela(resultado, passada)

    return rotas
