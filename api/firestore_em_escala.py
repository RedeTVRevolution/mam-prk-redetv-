"""Teste do Firestore em escala (#542): `gravar N`, `medir` e `apagar`, contra o dev.

Grava Jobs falsos (id `teste_NNNNNNN`), mede as listas do acervo com filtros combinados e
apaga tudo pelo intervalo de id. O risco que isto mede: dois filtros abrangentes com
interseção rara (um programa grande + estado raro) fazem a mescla de índices simples do
Firestore percorrer muito índice.

O Job falso é o `Job` de verdade, gravado por `model_dump()` como o `RepositorioFirestore`
grava; fica só no documento (nenhuma subcoleção, nada em Storage, BigQuery ou na busca). Nada
na coleção `jobs` dispara pipeline: o único gatilho do Eventarc é o do bucket da quarentena.
Os estados são só os finais (`concluido`, `falhou`, `cancelado`) e a criação é de 30 dias
a 3 anos atrás, para não cair na janela da taxa horária nem no topo da lista dos Jobs reais.
Sem teste automático contra a nuvem; a lógica pura é testada com dublê.
"""

import argparse
import hashlib
import logging
import os
import random
import statistics
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, get_args

from google.cloud.firestore_v1 import FieldFilter
from google.cloud.firestore_v1.bulk_writer import BulkWriterOptions
from google.cloud.firestore_v1.query import Query
from google.cloud.firestore_v1.query_profile import ExplainOptions

from api import log_estruturado
from api.bancos import cliente_do_firestore
from api.jobs import CodigoDeFalha, FiltroDeJobs, Job, palavras_do_nome
from api.nuvem import (
    COLECAO_DE_JOBS,
    RepositorioFirestore,
    listagem_por_mes_do_ambiente,
)

PREFIXO = "teste_"
# `_` é 0x5F; o próximo caractere (`` ` ``) fecha o intervalo `teste_*` sem pegar mais nada.
FIM_DO_INTERVALO = "teste" + chr(ord("_") + 1)
TETO_DE_N = 2_000_000
LOTE_DA_GRAVACAO = 5_000
LOTE_DO_APAGAR = 500

PROGRAMAS = [f"TESTE Programa {n:02d}" for n in range(1, 41)]
PROGRAMAS_GRANDES = 3  # os três primeiros: 35%, 20% e 10% dos Jobs
PROGRAMA_GRANDE = PROGRAMAS[0]
PROGRAMA_PEQUENO = PROGRAMAS[-1]
# Os 37 restantes dividem 35% por Zipf.
_PESOS_DOS_PEQUENOS = [1 / k for k in range(1, len(PROGRAMAS) - PROGRAMAS_GRANDES + 1)]
PESOS_DOS_PROGRAMAS = [35.0, 20.0, 10.0] + [
    35.0 * p / sum(_PESOS_DOS_PEQUENOS) for p in _PESOS_DOS_PEQUENOS
]
SISTEMAS = [None, "Playout", "Ingest", "Upload manual"]
PESOS_DOS_SISTEMAS = [20, 40, 30, 10]
PALAVRAS_COMUNS = ["bloco", "entrevista", "jornal", "externa", "abertura", "reportagem"]
PESOS_DAS_PALAVRAS = [40, 20, 15, 10, 8, 7]
PALAVRA_COMUM = PALAVRAS_COMUNS[0]
PALAVRA_RARA = "cena00042"  # ~1 Job em 40 mil
CHANCE_DE_FALHAR = 0.002  # em qualquer programa
CHANCE_DE_CANCELAR = (
    0.004  # só nos programas pequenos: com o grande, a interseção é vazia
)
ANOS_DE_EXIBICAO = 25
CODIGOS_DE_FALHA = list(get_args(CodigoDeFalha))


def id_do_job_falso(i: int) -> str:
    return f"{PREFIXO}{i:07d}"


def job_falso(i: int, agora: datetime) -> Job:
    """O i-ésimo Job falso, sempre o mesmo para o mesmo `i` e `agora` (regravar é idempotente)."""
    rng = random.Random(i)
    indice = rng.choices(range(len(PROGRAMAS)), PESOS_DOS_PROGRAMAS)[0]
    programa = PROGRAMAS[indice]
    sistema = rng.choices(SISTEMAS, PESOS_DOS_SISTEMAS)[0]
    exibicao = (agora - timedelta(days=rng.randrange(ANOS_DE_EXIBICAO * 365))).date()
    criado_em = agora - timedelta(
        days=rng.randrange(30, 3 * 365), seconds=rng.randrange(86_400)
    )
    sorteio = rng.random()
    codigo: Any = None
    estado: Any
    if sorteio < CHANCE_DE_FALHAR:
        estado, codigo = "falhou", rng.choice(CODIGOS_DE_FALHA)
    elif (
        indice >= PROGRAMAS_GRANDES and sorteio < CHANCE_DE_FALHAR + CHANCE_DE_CANCELAR
    ):
        estado = "cancelado"
    else:
        estado = "concluido"
    palavras = rng.choices(PALAVRAS_COMUNS, PESOS_DAS_PALAVRAS, k=rng.randrange(2, 5))
    if rng.random() < 0.5:
        palavras.append(f"cena{rng.randrange(20_000):05d}")
    if i % 40_000 == 42:
        palavras.append(PALAVRA_RARA)  # garante algumas ocorrências
    nome = f"{programa.replace(' ', '-')}_{exibicao:%Y%m%d}_{'_'.join(palavras)}.mxf"
    id_ = id_do_job_falso(i)
    concluido = estado == "concluido"
    return Job(
        id=id_,
        nome=nome,
        tamanho_bytes=rng.randrange(50_000_000, 20_000_000_000),
        sha256=hashlib.sha256(id_.encode()).hexdigest(),
        duracao_s=float(rng.randrange(30, 14_400)) if concluido else None,
        timecode_origem="00:00:00:00",
        taxa_de_quadros=29.97,
        estado=estado,
        codigo_falha=codigo,
        criado_por=f"sistema:{sistema}" if sistema else f"uid-teste-{i % 50}",
        criado_por_email=None if sistema else "teste@exemplo.invalid",
        sistema=sistema,
        programa=programa,
        palavras=palavras_do_nome(nome),
        data_exibicao=exibicao,
        versao_pipeline="2026.11.2" if concluido else None,
        criado_em=criado_em,
        atualizado_em=criado_em,
    )


def _entradas_do_valor(valor: Any) -> int:
    if isinstance(valor, dict):
        return sum(_entradas_do_valor(v) for v in valor.values())
    if isinstance(valor, list):
        return len(valor)  # `array-contains`: uma entrada por elemento
    return 2  # crescente e decrescente (o `null` também)


def entradas_automaticas(documento: dict[str, Any]) -> int:
    """Entradas dos índices simples que o Firestore cria sozinho, sem `cortes_ms` (isento em
    infra/modulos/mam/cortes_sem_indice.tf). Estimativa pela regra da documentação."""
    return sum(_entradas_do_valor(v) for k, v in documento.items() if k != "cortes_ms")


def entradas_compostas(documento: dict[str, Any]) -> int:
    """Entradas dos 10 índices compostos de `jobs` que sobram depois do #542: `acervo` (8: um
    de programa, sistema, estado e palavras, cada um com `criado_em` e com `data_exibicao`),
    `acervo_por_mes` (1: `mes_exibicao` + `criado_em`) e `teto_de_criacao` (1)."""
    palavras = len(documento["palavras"])
    return 2 + 2 + 2 + 2 * palavras + 1 + 1


def limites_do_apagar(colecao: Any) -> tuple[Any, Any]:
    """Os dois documentos que cercam os ids `teste_*`: `__name__` >= o primeiro e < o segundo."""
    return colecao.document(PREFIXO), colecao.document(FIM_DO_INTERVALO)


def _dos_falsos(colecao: Any) -> Any:
    ini, fim = limites_do_apagar(colecao)
    return colecao.where(filter=FieldFilter("__name__", ">=", ini)).where(
        filter=FieldFilter("__name__", "<", fim)
    )


def contar(colecao: Any) -> int:
    return int(_dos_falsos(colecao).count().get()[0][0].value)


def gravar(cliente: Any, quantos: int, agora: datetime | None = None) -> int:
    """Grava `quantos` Jobs falsos em lotes; devolve quantos o BulkWriter confirmou."""
    if not 0 < quantos <= TETO_DE_N:
        raise SystemExit(f"N entre 1 e {TETO_DE_N}")
    agora = agora or datetime.now(UTC)
    colecao = cliente.collection(COLECAO_DE_JOBS)
    escritor = cliente.bulk_writer(
        BulkWriterOptions(initial_ops_per_second=500, max_ops_per_second=2000)
    )
    feitos = [0]
    falhas = [0]
    escritor.on_write_result(lambda *_: feitos.__setitem__(0, feitos[0] + 1))
    escritor.on_write_error(lambda *_: falhas.__setitem__(0, falhas[0] + 1) or False)
    inicio = time.monotonic()
    for de in range(0, quantos, LOTE_DA_GRAVACAO):
        for i in range(de, min(de + LOTE_DA_GRAVACAO, quantos)):
            job = job_falso(i, agora)
            escritor.set(colecao.document(job.id), job.model_dump())
        escritor.flush()
        decorrido = time.monotonic() - inicio
        print(
            f"{feitos[0]}/{quantos} gravados, {feitos[0] / decorrido:.0f}/s, falhas {falhas[0]}"
        )
    escritor.close()
    return feitos[0]


def apagar(cliente: Any) -> int:
    """Apaga todo documento `teste_*` de `jobs` (só chaves lidas, em lotes de 500)."""
    colecao = cliente.collection(COLECAO_DE_JOBS)
    consulta = _dos_falsos(colecao).select([]).order_by("__name__")
    escritor = cliente.bulk_writer(
        BulkWriterOptions(initial_ops_per_second=500, max_ops_per_second=2000)
    )
    apagados = 0
    inicio = time.monotonic()
    while True:
        # Sem cursor: o que foi apagado já não volta na consulta seguinte.
        docs = list(consulta.limit(LOTE_DO_APAGAR).stream())
        if not docs:
            break
        for doc in docs:
            escritor.delete(doc.reference)
        escritor.flush()
        apagados += len(docs)
        print(f"{apagados} apagados, {apagados / (time.monotonic() - inicio):.0f}/s")
    escritor.close()
    return apagados


@dataclass(frozen=True)
class Caso:
    nome: str
    filtro: FiltroDeJobs


def casos(hoje: date) -> list[Caso]:
    def f(nome: str, **campos: Any) -> Caso:
        return Caso(nome, FiltroDeJobs(limite=50, so_os_da_lista=True, **campos))

    falhou, cancelado = frozenset({"falhou"}), frozenset({"cancelado"})
    ano = {"exibicao_de": hoje - timedelta(days=365), "exibicao_ate": hoje}
    cinco = {"exibicao_de": hoje - timedelta(days=5 * 365), "exibicao_ate": hoje}
    mes = {"exibicao_de": hoje - timedelta(days=30), "exibicao_ate": hoje}
    grande = {"programa": PROGRAMA_GRANDE}
    return [
        f("sem filtro"),
        f("sistema comum", sistema="Playout"),
        f("programa grande", **grande),
        f("programa pequeno", programa=PROGRAMA_PEQUENO),
        f("estado falhou (raro)", estados=falhou),
        f("estado falhou+cancelado", estados=falhou | cancelado),
        f("palavra comum", palavras=(PALAVRA_COMUM,)),
        f("palavra rara", palavras=(PALAVRA_RARA,)),
        f("RUIM grande + falhou", estados=falhou, **grande),
        f("RUIM grande + cancelado (vazio)", estados=cancelado, **grande),
        f(
            "RUIM grande + falhou + sistema",
            estados=falhou,
            sistema="Playout",
            **grande,
        ),
        f(
            "RUIM grande + falhou + palavra",
            estados=falhou,
            palavras=(PALAVRA_COMUM,),
            **grande,
        ),
        f(
            "grande + concluido (comum x comum)",
            estados=frozenset({"concluido"}),
            **grande,
        ),
        f("exibicao: sem filtro, 1 ano", ordem="exibicao", **ano),
        f(
            "exibicao: RUIM grande + falhou, 5 anos",
            ordem="exibicao",
            estados=falhou,
            **cinco,
            **grande,
        ),
        f(
            "exibicao: RUIM grande + cancelado, 5 anos",
            ordem="exibicao",
            estados=cancelado,
            **cinco,
            **grande,
        ),
        f("enviado: grande, ultimos 30 dias", **mes, **grande),
        f("enviado: RUIM grande + falhou, 5 anos", estados=falhou, **cinco, **grande),
    ]


@contextmanager
def explicando(coletor: list[Any]) -> Iterator[None]:
    """Faz todo `Query.stream` do cliente rodar com `explain_options(analyze=True)` e juntar as
    estatísticas em `coletor`, para medir as consultas reais de `nuvem.py` sem reescrevê-las."""
    original = Query.stream

    def stream(self: Any, *args: Any, **kwargs: Any) -> Iterator[Any]:
        gerador = original(
            self, *args, explain_options=ExplainOptions(analyze=True), **kwargs
        )

        def ler() -> Iterator[Any]:
            yield from gerador
            coletor.append(gerador.get_explain_metrics().execution_stats)

        return ler()

    Query.stream = stream  # type: ignore[method-assign,assignment]
    try:
        yield
    finally:
        Query.stream = original  # type: ignore[method-assign]


def _inteiro(valor: Any) -> int:
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return 0


def medir(repositorio: RepositorioFirestore, repeticoes: int, hoje: date) -> None:
    print(
        f"{'caso':<44}{'pág':>4}{'p50 ms':>8}{'máx ms':>8}{'leituras':>9}{'entradas':>10}{'volta':>6}"
    )
    for caso in casos(hoje):
        cursor: str | None = None
        for pagina in (1, 2):
            filtro = replace(caso.filtro, cursor=cursor)
            try:
                tempos = []
                for _ in range(repeticoes):
                    inicio = time.monotonic()
                    resultado = repositorio.consultar(filtro)
                    tempos.append((time.monotonic() - inicio) * 1000)
                estatisticas: list[Any] = []
                with explicando(estatisticas):
                    repositorio.consultar(filtro)
            except Exception as erro:  # noqa: BLE001
                print(
                    f"{caso.nome:<44}{pagina:>4}  ERRO {type(erro).__name__}: {str(erro)[:80]}"
                )
                break
            leituras = sum(e.read_operations for e in estatisticas)
            entradas = sum(
                _inteiro(e.debug_stats.get("index_entries_scanned"))
                for e in estatisticas
            )
            print(
                f"{caso.nome:<44}{pagina:>4}{statistics.median(tempos):>8.0f}{max(tempos):>8.0f}"
                f"{leituras:>9}{entradas:>10}{len(resultado.jobs):>6}"
            )
            cursor = resultado.proximo_cursor
            if cursor is None:
                break


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="firestore_em_escala")
    sub = parser.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("gravar")
    g.add_argument("n", type=int)
    m = sub.add_parser("medir")
    m.add_argument("--repeticoes", type=int, default=3)
    sub.add_parser("apagar")
    args = parser.parse_args(argv)

    cliente = cliente_do_firestore(os.environ["GCP_PROJECT_ID"])
    colecao = cliente.collection(COLECAO_DE_JOBS)
    print(f"Jobs falsos antes: {contar(colecao)}")
    if args.comando == "gravar":
        amostra = job_falso(0, datetime.now(UTC)).model_dump()
        print(
            f"Por Job: 1 documento, {entradas_automaticas(amostra)} entradas dos índices simples e "
            f"{entradas_compostas(amostra)} dos 10 compostos (estimativa)"
        )
        print(f"{gravar(cliente, args.n)} gravados")
    elif args.comando == "apagar":
        print(f"{apagar(cliente)} apagados")
    else:
        por_mes = listagem_por_mes_do_ambiente(os.environ)
        print(f"LISTAGEM_POR_MES={por_mes}")
        medir(
            RepositorioFirestore(cliente, listagem_por_mes=por_mes),
            args.repeticoes,
            datetime.now(UTC).date(),
        )
    print(f"Jobs falsos depois: {contar(colecao)}")
    return 0


if __name__ == "__main__":
    log_estruturado.configurar(logging.WARNING)
    sys.exit(main(sys.argv[1:]))
