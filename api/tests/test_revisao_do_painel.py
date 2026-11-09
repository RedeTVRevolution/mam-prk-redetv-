"""O tempo de revisão da aba Revisão no BigQuery (#467): a consulta única, o que a API
carrega, o espelho das medidas e a tabela do Terraform."""

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from api.custo_do_painel import CustoEmMemoria
from api.jobs import Job, RepositorioEmMemoria
from api.painel import NumerosDeRevisao, tempo_no_painel
from api.revisao import Medida, Pulso, RepositorioDeRevisaoEmMemoria
from api.revisao_do_painel import (
    ConfigDaRevisao,
    RepositorioDeRevisaoEspelhado,
    RevisaoBigQuery,
    RevisaoEmMemoria,
    RevisaoNoVideo,
    TabelaDaRevisaoBigQuery,
    TabelaDaRevisaoEmMemoria,
    agregar,
    preencher,
)
from api.tests.test_rotas_do_painel import Mundo

TF = (
    Path(__file__).parents[2] / "infra" / "modulos" / "mam" / "revisao_do_painel.tf"
).read_text()
AGORA = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
CONFIG = ConfigDaRevisao("proj", "decupagens", "regiao-x", "revisao", "jobs")


class _Transporte:
    def __init__(self, linhas: list[list[Any]]) -> None:
        self.corpos: list[dict[str, Any]] = []
        self._linhas = linhas

    def __call__(self, corpo: dict[str, Any]) -> dict[str, Any]:
        self.corpos.append(corpo)
        return {
            "jobComplete": True,
            "rows": [{"f": [{"v": v} for v in linha]} for linha in self._linhas],
        }


def _job(id: str, programa: str | None, duracao_s: float | None = None) -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=10,
        estado="concluido",
        criado_por="u1",
        programa=programa,
        duracao_s=duracao_s,
        criado_em=AGORA,
        atualizado_em=AGORA,
    )


def _medida(job: str, uid: str, ativo_s: float, duracao_s: float | None) -> Medida:
    return Medida(
        job_id=job,
        uid=uid,
        email=f"{uid}@x",
        ativo_s=ativo_s,
        sessoes=1,
        duracao_s=duracao_s,
        ultimo_pulso=AGORA,
    )


def _antes(medidas: list[RevisaoNoVideo]) -> NumerosDeRevisao:
    """O cálculo de antes (`_numeros_de_revisao` sobre uma linha por pessoa e vídeo)."""
    duracao: dict[str, float] = {}
    for m in medidas:
        if m.duracao_s:
            duracao[m.job_id] = max(duracao.get(m.job_id, 0), m.duracao_s)
    ativo_s = sum(m.ativo_s for m in medidas)
    com_duracao_s = sum(m.ativo_s for m in medidas if m.job_id in duracao)
    horas = sum(duracao.values()) / 3600
    return NumerosDeRevisao(
        minutos=round(ativo_s / 60, 2),
        videos=len({m.job_id for m in medidas}),
        horas_de_video=round(horas, 2),
        minutos_por_hora_de_video=(
            round(com_duracao_s / 60 / horas, 2) if horas else None
        ),
    )


MEDIDAS = [
    RevisaoNoVideo("v1", "bia", "bia@x", "Hoje", 600, 3600),
    RevisaoNoVideo("v1", "caio", "caio@x", "Hoje", 300, 3600),
    RevisaoNoVideo("v2", "bia", "bia@x", "Fala", 1200, 1800),
    RevisaoNoVideo("v3", "caio", "caio@x", "Fala", 120, None),
    RevisaoNoVideo("v4", "bia", "bia@x", None, 90, 900),
]


def test_a_revisao_agregada_e_a_do_calculo_antigo_nos_mesmos_jobs() -> None:
    painel = tempo_no_painel(agregar(MEDIDAS))

    assert painel.total == _antes(MEDIDAS)
    por_pessoa = {p.uid: p for p in painel.por_pessoa}
    for uid in ("bia", "caio"):
        proprias = [m for m in MEDIDAS if m.uid == uid]
        assert por_pessoa[uid].minutos == _antes(proprias).minutos
        assert (
            por_pessoa[uid].minutos_por_hora_de_video
            == _antes(proprias).minutos_por_hora_de_video
        )
    por_programa = {p.programa: p for p in painel.por_programa}
    for programa in ("Hoje", "Fala", None):
        proprias = [m for m in MEDIDAS if m.programa == programa]
        esperado = _antes(proprias)
        assert (
            por_programa[programa].model_dump(exclude={"programa"})
            == esperado.model_dump()
        )
    # O vídeo revisado por duas pessoas conta uma vez no total, uma em cada pessoa.
    assert painel.total.videos == 4
    assert sum(p.videos for p in painel.por_pessoa) == 5


def test_o_dubla_cruza_as_medidas_com_os_jobs_como_antes() -> None:
    jobs = RepositorioEmMemoria()
    jobs.salvar(_job("v1", "Hoje", duracao_s=1800))
    jobs.salvar(_job("v2", "Hoje"))
    revisao = RepositorioDeRevisaoEmMemoria()
    for m in (_medida("v1", "ana", 60, 3600), _medida("v2", "ana", 60, 3600)):
        revisao.aplicar(
            Pulso(
                job_id=m.job_id, uid=m.uid, email=m.email, quando=AGORA,
                evento="inicio", duracao_s=m.duracao_s,
            ),
            10_000,
        )  # fmt: skip
    revisao.aplicar(
        Pulso(job_id="v9", uid="ana", email="ana@x", quando=AGORA, evento="inicio"),
        10_000,
    )

    tempo = RevisaoEmMemoria(revisao, jobs).tempo(None, None, None, None)

    # v1 vale a duração do Job (1800), v2 a da medida (3600); v9 não tem Job.
    assert tempo.total.videos == 2
    assert tempo.total.horas == pytest.approx(1.5)


def test_a_consulta_e_uma_so_e_junta_a_revisao_com_os_jobs() -> None:
    transporte = _Transporte([])
    RevisaoBigQuery(CONFIG, transporte).tempo(
        AGORA, AGORA + timedelta(days=1), "Hoje", "ana"
    )

    assert len(transporte.corpos) == 1
    corpo = transporte.corpos[0]
    sql = corpo["query"]
    assert "`proj.decupagens.revisao`" in sql
    assert "JOIN `proj.decupagens.jobs`" in sql
    assert "r.ultimo_pulso >= @inicio" in sql and "r.ultimo_pulso < @fim" in sql
    assert "j.programa = @programa" in sql and "r.uid = @usuario" in sql
    assert "Hoje" not in sql and "ana" not in sql
    assert {
        p["name"]: p["parameterValue"]["value"] for p in corpo["queryParameters"]
    } == {
        "inicio": AGORA.isoformat(),
        "fim": (AGORA + timedelta(days=1)).isoformat(),
        "programa": "Hoje",
        "usuario": "ana",
    }
    assert corpo["location"] == "regiao-x"


def test_sem_filtro_a_consulta_nao_leva_parametros() -> None:
    transporte = _Transporte([])
    RevisaoBigQuery(CONFIG, transporte).tempo(None, None, None, None)

    assert transporte.corpos[0]["queryParameters"] == []
    assert "WHERE TRUE" in transporte.corpos[0]["query"]


def _linhas_do_bigquery(medidas: list[RevisaoNoVideo]) -> list[list[Any]]:
    """O que o BigQuery devolveria (os quatro agrupamentos), em texto como na API REST."""
    a = agregar(medidas)

    def linha(grao: str, uid: Any, email: Any, programa: Any, n: Any) -> list[Any]:
        return [grao, uid, email, programa, n.ativo_s, n.ativo_com_duracao_s,
                n.videos, n.horas]  # fmt: skip

    return [
        linha("total", None, None, None, a.total),
        *(linha("uid_email", u, e, None, n) for (u, e), n in a.por_pessoa.items()),
        *(linha("programa", None, None, p, n) for p, n in a.por_programa.items()),
        *(
            linha("uid_email_programa", u, e, p, n)
            for (u, e, p), n in a.por_pessoa_e_programa.items()
        ),
    ]


def test_a_resposta_do_bigquery_vira_o_mesmo_agregado() -> None:
    fonte = RevisaoBigQuery(CONFIG, _Transporte(_linhas_do_bigquery(MEDIDAS)))

    assert fonte.tempo(None, None, None, None) == agregar(MEDIDAS)


def test_o_sql_da_os_mesmos_quatro_graos_que_o_agregado_em_memoria() -> None:
    banco = sqlite3.connect(":memory:")
    try:
        banco.execute(
            "CREATE TABLE revisao (job_id, uid, email, ativo_s REAL, duracao_s REAL)"
        )
        banco.execute("CREATE TABLE jobs (id, programa, duracao_ms REAL)")
        banco.executemany(
            "INSERT INTO revisao VALUES (?, ?, ?, ?, ?)",
            [(m.job_id, m.uid, m.email, m.ativo_s, m.duracao_s) for m in MEDIDAS],
        )
        banco.executemany(
            "INSERT INTO jobs VALUES (?, ?, ?)",
            [
                (m.job_id, m.programa, m.duracao_s * 1000 if m.duracao_s else None)
                for m in {m.job_id: m for m in MEDIDAS}.values()
            ],
        )
        sql, _ = RevisaoBigQuery(CONFIG, _Transporte([])).consulta(
            None, None, None, None
        )
        sql = (
            sql.replace("`proj.decupagens.revisao`", "revisao")
            .replace("`proj.decupagens.jobs`", "jobs")
            .replace("CAST(NULL AS STRING)", "CAST(NULL AS TEXT)")
        )
        sql = re.sub(r"\bIF\(", "IIF(", sql)
        linhas = [list(linha) for linha in banco.execute(sql)]
    finally:
        banco.close()
    fonte = RevisaoBigQuery(CONFIG, _Transporte(linhas))

    assert fonte.tempo(None, None, None, None) == agregar(MEDIDAS)


def test_com_300_mil_jobs_a_api_carrega_so_as_linhas_do_agrupamento() -> None:
    programas = [f"P{i}" for i in range(10)]
    pessoas = [f"u{i}" for i in range(20)]
    medidas = [
        RevisaoNoVideo(
            f"v{i}",
            pessoas[i % 20],
            f"{pessoas[i % 20]}@x",
            programas[i % 10],
            60.0,
            1800.0,
        )
        for i in range(300_000)
    ]
    linhas = _linhas_do_bigquery(medidas)
    transporte = _Transporte(linhas)

    tempo = RevisaoBigQuery(CONFIG, transporte).tempo(
        datetime(2021, 11, 1, tzinfo=UTC), AGORA, None, None
    )

    # Cinco anos de 300 mil vídeos: a resposta tem uma linha por grupo, não por vídeo.
    assert tempo.total.videos == 300_000
    assert len(linhas) < 100
    assert len(linhas) == 1 + len(tempo.por_pessoa) + len(tempo.por_programa) + len(
        tempo.por_pessoa_e_programa
    )
    assert len(transporte.corpos) == 1


class _JobsSemListar(RepositorioEmMemoria):
    def listar(self) -> Any:
        raise AssertionError("o painel não pode ler a coleção jobs")


def test_nenhuma_rota_do_painel_le_a_colecao_jobs() -> None:
    jobs = _JobsSemListar()
    mundo = Mundo(
        ["diretoria"],
        jobs=jobs,
        faturamento=CustoEmMemoria([], []),
        tempo_de_revisao=RevisaoBigQuery(CONFIG, _Transporte([])),
    )

    # As rotas saem do app: uma rota nova do painel entra no teste sem ninguém lembrar.
    rotas = [
        caminho.removeprefix("/v1/painel")
        for caminho, metodos in mundo.cliente.get("/openapi.json")
        .json()["paths"]
        .items()
        if caminho.startswith("/v1/painel/") and "get" in metodos
    ]
    assert {"/revisao", "/custo", "/fila"} <= set(rotas)
    for rota in rotas:
        assert mundo.get(rota).status_code == 200, rota
    assert mundo.get("/revisao", formato="csv").status_code == 200


def test_periodo_sem_medidas_da_zero_e_nao_erro() -> None:
    # O BigQuery devolve a linha do total mesmo sem medida, com as somas que não têm IFNULL
    # vindo NULL; a consulta as zera.
    transporte = _Transporte([["total", None, None, None, "0", "0", "0", "0"]])

    tempo = RevisaoBigQuery(CONFIG, transporte).tempo(None, None, None, None)

    assert tempo == agregar([])
    assert "IFNULL(SUM(ativo_s), 0) AS ativo_s" in transporte.corpos[0]["query"]


def test_cada_pulso_vai_para_a_tabela_e_a_tabela_guarda_a_mais_nova() -> None:
    tabela = TabelaDaRevisaoEmMemoria()
    repositorio = RepositorioDeRevisaoEspelhado(RepositorioDeRevisaoEmMemoria(), tabela)
    base: dict[str, Any] = {"job_id": "v1", "uid": "ana", "email": "ana@x"}

    repositorio.aplicar(Pulso(**base, quando=AGORA, evento="inicio"), 10_000)
    repositorio.aplicar(
        Pulso(**base, quando=AGORA + timedelta(seconds=60), evento="atividade"), 10_000
    )

    assert tabela.por_chave[("v1", "ana")].ativo_s == 60
    tabela.gravar(
        [_medida("v1", "ana", 5, None).model_copy(update={"ultimo_pulso": AGORA})]
    )
    assert tabela.por_chave[("v1", "ana")].ativo_s == 60


def test_a_tabela_fora_do_ar_nao_derruba_o_pulso() -> None:
    class Quebrada:
        def gravar(self, medidas: list[Medida]) -> None:
            raise RuntimeError("BigQuery fora")

    revisao = RepositorioDeRevisaoEmMemoria()
    repositorio = RepositorioDeRevisaoEspelhado(revisao, Quebrada())

    medida = repositorio.aplicar(
        Pulso(job_id="v1", uid="ana", email="ana@x", quando=AGORA, evento="inicio"),
        10_000,
    )

    assert medida.sessoes == 1
    assert [m.uid for m in revisao.do_video("v1")] == ["ana"]


def test_preencher_traz_as_medidas_antigas_em_lotes_e_repetir_nao_muda() -> None:
    revisao = RepositorioDeRevisaoEmMemoria()
    for i in range(5):
        revisao.aplicar(
            Pulso(
                job_id=f"v{i}", uid="ana", email="ana@x", quando=AGORA, evento="inicio"
            ),
            10_000,
        )
    tabela = TabelaDaRevisaoEmMemoria()

    assert preencher(revisao, tabela, por_lote=2) == 5
    primeira = dict(tabela.por_chave)
    assert preencher(revisao, tabela, por_lote=2) == 5

    assert len(primeira) == 5 and tabela.por_chave == primeira


def test_o_merge_troca_so_pela_medida_mais_nova_e_leva_tudo_por_parametro() -> None:
    transporte = _Transporte([])
    TabelaDaRevisaoBigQuery(CONFIG, transporte).gravar(
        [_medida("v1", "a'; DROP TABLE x; --", 60, 3600)]
    )

    corpo = transporte.corpos[0]
    sql = corpo["query"]
    assert "MERGE `proj.decupagens.revisao`" in sql
    assert "ON t.job_id = s.job_id AND t.uid = s.uid" in sql
    assert "WHEN MATCHED AND s.ultimo_pulso >= t.ultimo_pulso" in sql
    assert "DROP TABLE" not in sql
    assert "DROP TABLE" in corpo["queryParameters"][0]["parameterValue"]["value"]


def test_as_colunas_do_terraform_sao_as_que_a_carga_e_a_consulta_usam() -> None:
    nomes = re.findall(r'^    \{ name = "(\w+)"', TF, re.MULTILINE)

    assert nomes == ["job_id", "uid", "email", "ativo_s", "duracao_s", "ultimo_pulso"]
    assert set(nomes) == set(_json_da_medida_campos())


def _json_da_medida_campos() -> list[str]:
    from api.revisao_do_painel import _json_da_medida

    return list(_json_da_medida(_medida("v1", "ana", 1, None)))


def test_a_tabela_e_particionada_pelo_ultimo_pulso_e_agrupada_por_pessoa() -> None:
    bloco = TF[TF.index('resource "google_bigquery_table" "revisao_do_painel"') :]
    bloco = bloco[: bloco.index("\n}\n")]

    assert re.search(r'type\s*=\s*"DAY"', bloco)
    assert re.search(r'field\s*=\s*"ultimo_pulso"', bloco)
    assert re.search(r'clustering\s*=\s*\["uid",\s*"job_id"\]', bloco)
    assert "deletion_protection = true" in bloco
    assert "local.tabela_de_revisao_do_painel" in bloco
    assert 'output "bigquery_tabela_de_revisao"' in TF


def test_o_ambiente_da_web_recebe_o_nome_da_tabela_do_terraform() -> None:
    infra = Path(__file__).parents[2] / "infra"
    main = (infra / "modulos" / "mam" / "main.tf").read_text()

    assert 'name  = "BIGQUERY_TABELA_DE_REVISAO"' in main
    assert "tabela_de_revisao_do_painel = " in main
    assert 'output "bigquery_tabela_de_revisao"' in (infra / "main.tf").read_text()
