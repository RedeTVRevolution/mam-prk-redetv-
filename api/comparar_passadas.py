"""`make comparar-passadas` (#248): a decupagem do Job contra uma passada de comparação.

    python -m api.comparar_passadas JOBS [PASSADA] [MODELO] [PASTA]

`JOBS` é um Job ou vários separados por vírgula (o relatório do piloto inteiro, com a soma
por requisito). Sem `PASSADA`, vale a última passada de cada Job (só do `MODELO`, se vier);
com ela, o id exato (só faz sentido com um Job). Grava em `PASTA` (`comparacao-passadas`)
um Markdown e um JSON.

Por requisito (famosos, menções, pautas, B-roll, comerciais) o relatório traz os itens que
só um lado tem, os que os dois têm com diferença (nome, tipo, marca ou tempo fora da
tolerância do `api/comparador.py`) e as contagens; o pareamento é o do comparador. O lado A
é a decupagem do Job e o B, a passada. Timecode é o erro de início e de fim dos itens
pareados, inclusive os de nome trocado (média e p95 sobre os erros de início e de fim
juntos; fora da tolerância conta o par pelo maior dos dois). O custo é por hora de vídeo e
o tempo, por etapa e total, de cada lado.

O Job não guarda os tokens que gastou: os do lado A vêm de `TOKENS_DO_JOB`
(`job=entrada:saida`, separados por vírgula) e, sem eles, o custo do Job sai "n/d". Vem do
ambiente (o Makefile lê os nomes do Terraform): `GCP_PROJECT_ID`, `BUCKET_ACEITOS`,
`BUCKET_DECUPAGENS`, `PRECOS_DOS_MODELOS` (`modelo=entrada:saida`, US$ por milhão de
tokens), `DATA_DA_TABELA_DE_PRECOS` (a data da tabela consultada) e, opcionais,
`MODELO_DO_JOB` (o do Job, `api.gemini.MODELO` por padrão) e `TOKENS_DO_JOB`.
"""

import json
import math
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.comparador import (
    TIPOS_COM_IDENTIDADE,
    TOLERANCIA_MS,
    Item,
    Pareado,
    itens_do_modelo,
    normalizar,
    parear,
)
from api.comparar_objetos import (
    FaltaNoAmbiente,
    Preco,
    exigir_do_ambiente,
    precos_do_ambiente,
)
from api.decupagem import Decupagem
from api.gemini import MODELO
from api.jobs import Job, RepositorioDeJobs
from api.nuvem import DecupagensStorage, RepositorioFirestore
from api.passadas import LeituraDePassadas, Passada, PassadasStorage

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
    sobra_b = list(b)
    pares: list[Pareado] = []
    repetidos: list[Item] = []
    for p in pareados:
        if p.modelo in sobra_b:
            sobra_b.remove(p.modelo)
            pares.append(p)
        else:
            repetidos.append(p.gabarito)
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
    iguais = 0
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
        if motivos:
            diferentes.append(
                Diferenca(
                    _entrada(job_id, ia, detalhes_a),
                    _entrada(job_id, ib, detalhes_b),
                    motivos,
                )
            )
        else:
            iguais += 1
    return _Comparacao(
        Requisito(
            nome=nome,
            contagem_a=len(a),
            contagem_b=len(b),
            iguais=iguais,
            so_em_a=[_entrada(job_id, i, detalhes_a) for i in sem_par_a],
            so_em_b=[_entrada(job_id, i, detalhes_b) for i in sem_par_b],
            diferentes=diferentes,
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


def custo_do_job(
    tokens: tuple[int, int] | None, modelo: str, preco: Preco | None
) -> Custo | None:
    if tokens is None or preco is None:
        return None
    entrada, saida = tokens
    return Custo(
        entrada,
        saida,
        round(entrada * preco.entrada / 1e6 + saida * preco.saida / 1e6, 6),
        [PrecoUsado(modelo, preco.entrada, preco.saida)],
    )


def tokens_do_job(texto: str) -> dict[str, tuple[int, int]]:
    """`TOKENS_DO_JOB`: `job=entrada:saida`, separados por vírgula."""
    tokens: dict[str, tuple[int, int]] = {}
    for item in filter(None, (p.strip() for p in texto.split(","))):
        job, _, valores = item.partition("=")
        entrada, _, saida = valores.partition(":")
        try:
            tokens[job] = (int(entrada), int(saida))
        except ValueError as e:
            raise FaltaNoAmbiente(f"tokens inválidos em TOKENS_DO_JOB: {item!r}") from e
    return tokens


def escolher_passada(
    passadas: LeituraDePassadas, job_id: str, passada_id: str | None, modelo: str | None
) -> Passada:
    if passada_id:
        achada = passadas.ler_passada(job_id, passada_id)
        if achada is None:
            raise ValueError(f"Job {job_id}: não há a passada {passada_id}")
        return achada
    resumos = [
        r for r in passadas.listar_passadas(job_id) if modelo in (None, "", r.modelo)
    ]
    if not resumos:
        raise ValueError(
            f"Job {job_id}: nenhuma passada" + (f" de {modelo}" if modelo else "")
        )
    ultima = max(resumos, key=lambda r: r.criada_em)
    achada = passadas.ler_passada(job_id, ultima.id)
    if achada is None:
        raise ValueError(f"Job {job_id}: a passada {ultima.id} sumiu")
    return achada


def comparar(
    job_ids: Sequence[str],
    *,
    passada_id: str | None,
    modelo: str | None,
    repositorio: RepositorioDeJobs,
    ler_decupagem: Callable[[str], Decupagem | None],
    passadas: LeituraDePassadas,
    custo_do_job_por_id: Callable[[str], Custo | None],
    tabela_de_precos_em: str,
    agora: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Relatorio:
    feitos: list[ResultadoDoJob] = []
    for job_id in job_ids:
        job = repositorio.obter(job_id)
        if job is None or job.estado != "concluido" or job.duracao_s is None:
            raise ValueError(f"O Job {job_id} não está concluído.")
        decupagem = ler_decupagem(job_id)
        if decupagem is None:
            raise ValueError(f"O Job {job_id} não tem Decupagem.")
        passada = escolher_passada(passadas, job_id, passada_id, modelo)
        resultado = comparar_decupagens(
            job_id,
            round(job.duracao_s * 1000),
            decupagem,
            passada.decupagem,
            LadoDoResultado(custo_do_job_por_id(job_id), tempo_do_job(job)),
            lado_da_passada(passada),
        )
        feitos.append(ResultadoDoJob(job_id, passada.id, passada.modelo, resultado))
    return Relatorio(
        gerado_em=agora(),
        tabela_de_precos_em=tabela_de_precos_em,
        jobs=feitos,
        total=somar([f.resultado for f in feitos]),
    )


def relatorio_em_json(relatorio: Relatorio) -> str:
    def preparar(r: Resultado) -> dict[str, Any]:
        corpo = asdict(r)
        for lado in ("a", "b"):
            corpo[lado]["custo_por_hora_usd"] = custo_por_hora(
                getattr(r, lado).custo, r.duracao_ms
            )
        return corpo

    return json.dumps(
        {
            "gerado_em": relatorio.gerado_em.isoformat(),
            "tabela_de_precos_em": relatorio.tabela_de_precos_em,
            "lados": {"a": LADO_A, "b": LADO_B},
            "jobs": [
                {
                    "job_id": j.job_id,
                    "passada": j.passada_id,
                    "modelo": j.modelo,
                    "resultado": preparar(j.resultado),
                }
                for j in relatorio.jobs
            ],
            "total": preparar(relatorio.total),
        },
        ensure_ascii=False,
        indent=2,
    )


_TITULOS = {
    "famosos": "Famosos (aparições com nome)",
    "mencoes": "Menções",
    "pautas": "Pautas",
    "broll_limpos": "B-roll: planos limpos",
    "broll_descricoes": "B-roll: descrições dos planos",
    "comerciais": "Comerciais",
}


def _tempo_em_s(ms: int) -> str:
    return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}"


def _linha(e: Entrada) -> str:
    detalhe = f" [{e.detalhe}]" if e.detalhe else ""
    return (
        f"{e.identidade or '(sem descrição)'}{detalhe} "
        f"{_tempo_em_s(e.inicio_ms)}–{_tempo_em_s(e.fim_ms)} ({e.job_id})"
    )


def _usd(valor: float | None) -> str:
    return f"US$ {valor:.4f}" if valor is not None else "n/d"


def _custo(lado: LadoDoResultado, duracao_ms: int) -> str:
    c = lado.custo
    if c is None:
        return "n/d (o Job não guarda os tokens)"
    precos = "; ".join(
        f"{p.modelo} a US$ {p.entrada}/{p.saida} por milhão" for p in c.precos
    )
    return (
        f"{c.tokens_de_entrada} tokens de entrada e {c.tokens_de_saida} de saída, "
        f"{_usd(c.usd)} no total, **{_usd(custo_por_hora(c, duracao_ms))} por hora de "
        f"vídeo** ({precos})"
    )


def _tempo(t: Tempo) -> str:
    etapas = ", ".join(f"{n} {s}s" for n, s in t.etapas.items()) or "sem etapas"
    return f"**{t.total_s}s no total** ({etapas})"


def _secao_do_resultado(r: Resultado, titulo: str, nivel: str) -> list[str]:
    saida = [f"{nivel} {titulo}", ""]
    saida.append(f"Vídeo: {r.duracao_ms / 3_600_000:.3f} h.")
    saida.append("")
    saida.append(
        "| Requisito | Job | Passada | Iguais | Diferentes | Só no Job | Só na passada |"
    )
    saida.append("|---|---|---|---|---|---|---|")
    for n in REQUISITOS:
        q = r.requisitos[n]
        saida.append(
            f"| {_TITULOS[n]} | {q.contagem_a} | {q.contagem_b} | {q.iguais} | "
            f"{len(q.diferentes)} | {len(q.so_em_a)} | {len(q.so_em_b)} |"
        )
    saida.append("")
    t = r.timecode
    media = f"{t.media_ms / 1000:.2f} s" if t.media_ms is not None else "n/d"
    p95 = f"{t.p95_ms / 1000:.2f} s" if t.p95_ms is not None else "n/d"
    saida.append(
        f"Timecode ({t.pares} itens pareados): erro médio {media}, p95 {p95}, "
        f"{t.fora_da_tolerancia} fora da tolerância de {t.tolerancia_ms / 1000:g} s."
    )
    saida.append("")
    saida.append(f"- Custo, Job: {_custo(r.a, r.duracao_ms)}")
    saida.append(f"- Custo, passada: {_custo(r.b, r.duracao_ms)}")
    saida.append(f"- Tempo, Job: {_tempo(r.a.tempo)}")
    saida.append(f"- Tempo, passada: {_tempo(r.b.tempo)}")
    saida.append("")
    for n in REQUISITOS:
        q = r.requisitos[n]
        if not (q.so_em_a or q.so_em_b or q.diferentes):
            continue
        saida.append(f"{nivel}# {_TITULOS[n]}")
        saida.append("")
        for d in q.diferentes:
            saida.append(
                f"- Diferença ({', '.join(d.motivos)}): Job {_linha(d.a)} × passada {_linha(d.b)}"
            )
        saida += [f"- Só no Job: {_linha(e)}" for e in q.so_em_a]
        saida += [f"- Só na passada: {_linha(e)}" for e in q.so_em_b]
        saida.append("")
    return saida


def relatorio_em_markdown(relatorio: Relatorio) -> str:
    saida = [
        "# Comparação do Job com a passada",
        "",
        (
            f"Gerado em {relatorio.gerado_em:%Y-%m-%d %H:%M} UTC. Tabela de preços de "
            f"{relatorio.tabela_de_precos_em}. Lado A: a decupagem do Job; lado B: a passada."
        ),
        "",
    ]
    if len(relatorio.jobs) > 1:
        saida += _secao_do_resultado(
            relatorio.total, f"Total de {len(relatorio.jobs)} Jobs", "##"
        )
    for j in relatorio.jobs:
        saida += _secao_do_resultado(
            j.resultado, f"Job {j.job_id}, passada {j.passada_id} ({j.modelo})", "##"
        )
    return "\n".join(saida)


def gravar(relatorio: Relatorio, pasta: Path) -> tuple[Path, Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    nome = (
        f"{relatorio.jobs[0].job_id}-{relatorio.jobs[0].passada_id}"
        if len(relatorio.jobs) == 1
        else f"piloto-{relatorio.gerado_em:%Y%m%dT%H%M%S}"
    )
    md, js = pasta / f"{nome}.md", pasta / f"{nome}.json"
    md.write_text(relatorio_em_markdown(relatorio), encoding="utf-8")
    js.write_text(relatorio_em_json(relatorio), encoding="utf-8")
    return md, js


def main(argumentos: list[str], ambiente: Mapping[str, str] = os.environ) -> int:
    if not 1 <= len(argumentos) <= 4:
        print(
            "uso: python -m api.comparar_passadas JOBS [PASSADA] [MODELO] [PASTA]",
            file=sys.stderr,
        )
        return 2
    argumentos = [*argumentos, "", "", ""][:4]
    jobs = [j.strip() for j in argumentos[0].split(",") if j.strip()]
    passada_id, modelo = argumentos[1] or None, argumentos[2] or None
    pasta = Path(argumentos[3] or "comparacao-passadas")
    if not jobs:
        print("erro: falta JOB ou JOBS", file=sys.stderr)
        return 2
    if passada_id and len(jobs) > 1:
        print("erro: PASSADA vale para um Job só", file=sys.stderr)
        return 2
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        aceitos = exigir_do_ambiente(ambiente, "BUCKET_ACEITOS")
        decupagens = exigir_do_ambiente(ambiente, "BUCKET_DECUPAGENS")
        precos = precos_do_ambiente(exigir_do_ambiente(ambiente, "PRECOS_DOS_MODELOS"))
        tabela = exigir_do_ambiente(ambiente, "DATA_DA_TABELA_DE_PRECOS")
        modelo_do_job = ambiente.get("MODELO_DO_JOB") or MODELO
        tokens = tokens_do_job(ambiente.get("TOKENS_DO_JOB", ""))
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    cliente = ClienteStorage(project=projeto)
    try:
        relatorio = comparar(
            jobs,
            passada_id=passada_id,
            modelo=modelo,
            repositorio=RepositorioFirestore(firestore.Client(project=projeto)),
            ler_decupagem=DecupagensStorage(cliente, aceitos, decupagens).ler_decupagem,
            passadas=PassadasStorage(cliente, aceitos, decupagens),
            custo_do_job_por_id=lambda j: custo_do_job(
                tokens.get(j), modelo_do_job, precos.get(modelo_do_job)
            ),
            tabela_de_precos_em=tabela,
        )
    except ValueError as e:  # pydantic.ValidationError é ValueError
        print(f"erro: {e}", file=sys.stderr)
        return 1
    md, js = gravar(relatorio, pasta)
    print(f"relatório em {md} e {js}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
