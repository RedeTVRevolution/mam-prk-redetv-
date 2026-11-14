"""`make comparar-passadas` (#248): a decupagem do Job contra uma passada de comparação.

    python -m api.ferramentas.comparar_passadas JOBS [PASSADA] [MODELO] [PASTA]

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
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.cloud.storage import Client as ClienteStorage

from api.ambiente import FaltaNoAmbiente, exigir_do_ambiente
from api.bancos import cliente_do_firestore
from api.comparacao_de_passadas import (
    LADO_A,
    LADO_B,
    REQUISITOS,
    Custo,
    Entrada,
    LadoDoResultado,
    PrecoUsado,
    Relatorio,
    Resultado,
    ResultadoDoJob,
    Tempo,
    comparar_decupagens,
    custo_por_hora,
    lado_da_passada,
    somar,
    tempo_do_job,
)
from api.decupagem import Decupagem
from api.ferramentas.comum import dolar
from api.gemini import MODELO
from api.jobs import RepositorioDeJobs
from api.nuvem import DecupagensStorage, RepositorioFirestore
from api.passadas import LeituraDePassadas, Passada, PassadasStorage
from api.precos_dos_modelos import Preco, lista_de_pares, precos_do_ambiente


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
    return lista_de_pares(texto, int, "tokens inválidos em TOKENS_DO_JOB")


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
    return dolar(valor, casas=4, ptbr=False) if valor is not None else "n/d"


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
            "uso: python -m api.ferramentas.comparar_passadas JOBS [PASSADA] [MODELO] [PASTA]",
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
        cliente = ClienteStorage(project=projeto)
        leitor = DecupagensStorage.do_ambiente(ambiente, cliente)
        precos = precos_do_ambiente(exigir_do_ambiente(ambiente, "PRECOS_DOS_MODELOS"))
        tabela = exigir_do_ambiente(ambiente, "DATA_DA_TABELA_DE_PRECOS")
        modelo_do_job = ambiente.get("MODELO_DO_JOB") or MODELO
        tokens = tokens_do_job(ambiente.get("TOKENS_DO_JOB", ""))
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    try:
        relatorio = comparar(
            jobs,
            passada_id=passada_id,
            modelo=modelo,
            repositorio=RepositorioFirestore(cliente_do_firestore(projeto)),
            ler_decupagem=leitor.ler_decupagem,
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
