"""As tabelas resumidas do painel (#280): o SQL roda no SQLite sobre eventos montados à mão."""

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from api.eventos_de_uso import EventoDeUso

MODULO = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
SQL = (MODULO / "resumos_de_uso.sql").read_text()
TF = (MODULO / "resumos_de_uso.tf").read_text()
HORA_MS = 3_600_000
COLUNAS = list(EventoDeUso.model_fields)


def _dia_de_sao_paulo(quando: str, fuso: str) -> str:
    assert fuso == "America/Sao_Paulo"
    return datetime.fromisoformat(quando).astimezone(ZoneInfo(fuso)).date().isoformat()


def _banco() -> sqlite3.Connection:
    banco = sqlite3.connect(":memory:")
    # A única função do BigQuery que o SQL usa e o SQLite não tem.
    banco.create_function("DATE", 2, _dia_de_sao_paulo)
    # As colunas são as do evento (e da tabela, que `test_infra_eventos_de_uso` confere):
    # o SQL que ler uma coluna que o evento não tem falha aqui.
    banco.execute(f"CREATE TABLE eventos_de_uso ({', '.join(COLUNAS)})")
    banco.execute("CREATE TABLE momentos (job_id, duracao_do_video_ms)")
    return banco


def _evento(
    banco: sqlite3.Connection, id: str, tipo: str, quando: str, quem: str, **resto: Any
) -> None:
    linha = {
        "id": id,
        "tipo": tipo,
        "quando": quando,
        "quem_tipo": "usuario",
        "quem_id": quem,
        **resto,
    }
    banco.execute(
        f"INSERT INTO eventos_de_uso ({', '.join(linha)}) "
        f"VALUES ({', '.join('?' * len(linha))})",
        list(linha.values()),
    )


def _resumir(banco: sqlite3.Connection) -> None:
    sql = (
        SQL.replace("${prefixo}", "")
        .replace("${tabela_de_eventos}", "eventos_de_uso")
        .replace("${tabela_de_momentos}", "momentos")
    )
    # O SQLite não tem CREATE OR REPLACE TABLE: troca por apagar e criar.
    sql = re.sub(
        r"CREATE OR REPLACE TABLE `(\w+)`",
        r"DROP TABLE IF EXISTS `\1`;\nCREATE TABLE `\1`",
        sql,
    )
    banco.executescript(sql)


def _tabela(banco: sqlite3.Connection, nome: str, ordem: str) -> list[dict[str, Any]]:
    cursor = banco.execute(f"SELECT * FROM {nome} ORDER BY {ordem}")
    nomes = [c[0] for c in cursor.description]
    return [dict(zip(nomes, linha, strict=True)) for linha in cursor.fetchall()]


@pytest.fixture
def banco() -> sqlite3.Connection:
    b = _banco()
    # Dia 1 (em São Paulo): Ana entra, envia o vídeo v1 (2 h) e o vídeo v2 (que falha e
    # não tem momentos copiados), busca duas vezes e corrige uma vez.
    _evento(b, "e1", "login", "2026-11-01T12:00:00+00:00", "ana")
    _evento(
        b,
        "e2",
        "envio",
        "2026-11-01T12:05:00+00:00",
        "ana",
        job_id="v1",
        programa="Hoje",
    )
    _evento(
        b,
        "e3",
        "envio",
        "2026-11-01T12:06:00+00:00",
        "ana",
        job_id="v2",
        programa="Hoje",
    )
    _evento(b, "e4", "busca", "2026-11-01T13:00:00+00:00", "ana")
    _evento(b, "e5", "busca", "2026-11-01T13:01:00+00:00", "ana", programa="Hoje")
    _evento(
        b,
        "e6",
        "correcao",
        "2026-11-01T14:00:00+00:00",
        "ana",
        job_id="v1",
        programa="Hoje",
    )
    # Dia 1: Beto entra e o sistema `cms` envia e chama a API.
    _evento(b, "e7", "login", "2026-11-01T15:00:00+00:00", "beto")
    _evento(
        b,
        "e8",
        "envio",
        "2026-11-01T15:01:00+00:00",
        "cms",
        quem_tipo="sistema",
        job_id="v3",
        programa="Fala",
    )
    _evento(
        b,
        "e9",
        "chamada_de_api",
        "2026-11-01T15:01:00+00:00",
        "cms",
        quem_tipo="sistema",
        metodo="POST",
        rota="/v1/jobs",
        status=202,
    )
    # Fim de processamento: v1 concluiu, v2 falhou, v3 concluiu.
    _evento(
        b,
        "e10",
        "fim_de_processamento",
        "2026-11-01T16:00:00+00:00",
        "ana",
        job_id="v1",
        programa="Hoje",
        estado="concluido",
    )
    _evento(
        b,
        "e11",
        "fim_de_processamento",
        "2026-11-01T16:00:00+00:00",
        "ana",
        job_id="v2",
        programa="Hoje",
        estado="falhou",
        codigo_falha="X",
    )
    _evento(
        b,
        "e12",
        "fim_de_processamento",
        "2026-11-01T16:30:00+00:00",
        "cms",
        quem_tipo="sistema",
        job_id="v3",
        programa="Fala",
        estado="concluido",
    )
    # Dia 2: 02:00 UTC ainda é dia 1 em São Paulo (-03:00); 03:00 UTC já é o dia 2.
    _evento(b, "e13", "login", "2026-11-02T02:00:00+00:00", "ana")
    _evento(b, "e14", "login", "2026-11-02T03:00:00+00:00", "ana")
    _evento(b, "e15", "busca", "2026-11-02T13:00:00+00:00", "beto")
    b.executemany(
        "INSERT INTO momentos VALUES (?, ?)",
        [("v1", 2 * HORA_MS), ("v1", 2 * HORA_MS), ("v3", HORA_MS)],
    )
    return b


def test_por_dia_e_usuario_conta_cada_indicador(banco: sqlite3.Connection) -> None:
    _resumir(banco)

    linhas = _tabela(banco, "uso_por_dia_e_usuario", "dia, quem_id")

    chaves = [(r["dia"], r["quem_id"]) for r in linhas]
    assert chaves == [
        ("2026-11-01", "ana"),
        ("2026-11-01", "beto"),
        ("2026-11-01", "cms"),
        ("2026-11-02", "ana"),
        ("2026-11-02", "beto"),
    ]
    ana = linhas[0]
    assert ana["acessos"] == 2  # o login das 02:00 UTC do dia 2 é do dia 1 em São Paulo
    assert ana["videos_enviados"] == 2
    assert ana["videos_concluidos"] == 1
    assert ana["videos_falhos"] == 1
    assert ana["horas_concluidas"] == 2.0
    assert ana["buscas"] == 2
    assert ana["correcoes"] == 1
    assert ana["chamadas_de_api"] == 0
    cms = linhas[2]
    assert cms["quem_tipo"] == "sistema"
    assert (
        cms["videos_enviados"],
        cms["videos_concluidos"],
        cms["chamadas_de_api"],
    ) == (1, 1, 1)
    assert cms["horas_concluidas"] == 1.0


def test_o_dia_e_o_de_sao_paulo(banco: sqlite3.Connection) -> None:
    _resumir(banco)

    por_dia = _tabela(banco, "uso_por_dia", "dia")

    assert [r["dia"] for r in por_dia] == ["2026-11-01", "2026-11-02"]
    assert por_dia[0]["acessos"] == 3  # ana (x2) e beto
    assert por_dia[1]["acessos"] == 1


def test_por_dia_conta_usuarios_ativos_sem_os_sistemas(
    banco: sqlite3.Connection,
) -> None:
    _resumir(banco)

    dia1, dia2 = _tabela(banco, "uso_por_dia", "dia")

    assert dia1["usuarios_ativos"] == 2  # ana e beto; o cms não conta
    assert dia2["usuarios_ativos"] == 2
    assert dia1["videos_enviados"] == 3
    assert dia1["videos_concluidos"] == 2
    assert dia1["videos_falhos"] == 1
    assert dia1["horas_concluidas"] == 3.0
    assert dia1["buscas"] == 2 and dia2["buscas"] == 1
    assert dia1["chamadas_de_api"] == 1


def test_o_fim_de_processamento_sozinho_nao_faz_ninguem_ativo(
    banco: sqlite3.Connection,
) -> None:
    # O v1 de Ana, reprocessado, termina no dia 3; ela não faz mais nada nesse dia.
    _evento(
        banco,
        "e20",
        "fim_de_processamento",
        "2026-11-03T16:00:00+00:00",
        "ana",
        job_id="v1",
        programa="Hoje",
        estado="falhou",
    )
    _resumir(banco)

    dia3 = _tabela(banco, "uso_por_dia", "dia")[2]
    ana = _tabela(banco, "uso_por_usuario", "quem_id")[0]

    assert (dia3["dia"], dia3["videos_falhos"]) == ("2026-11-03", 1)
    assert dia3["usuarios_ativos"] == 0
    assert ana["dias_ativos"] == 2


def test_por_usuario_traz_dias_ativos_e_ultimo_acesso(
    banco: sqlite3.Connection,
) -> None:
    _resumir(banco)

    ana, beto, cms = _tabela(banco, "uso_por_usuario", "quem_id")

    assert ana["dias_ativos"] == 2
    assert ana["acessos"] == 3
    assert ana["videos_enviados"] == 2 and ana["horas_concluidas"] == 2.0
    assert ana["ultimo_acesso"] == "2026-11-02T03:00:00+00:00"
    assert beto["dias_ativos"] == 2 and beto["buscas"] == 1
    assert cms["ultimo_acesso"] is None
    assert cms["chamadas_de_api"] == 1


def test_por_programa_deixa_de_fora_o_evento_sem_programa(
    banco: sqlite3.Connection,
) -> None:
    _resumir(banco)

    fala, hoje = _tabela(banco, "uso_por_dia_e_programa", "programa")

    assert (hoje["dia"], hoje["programa"]) == ("2026-11-01", "Hoje")
    assert hoje["videos_enviados"] == 2
    assert hoje["videos_concluidos"] == 1
    assert hoje["videos_falhos"] == 1
    assert hoje["horas_concluidas"] == 2.0
    assert hoje["buscas"] == 1  # a outra busca não tem programa
    assert hoje["correcoes"] == 1
    assert (fala["videos_enviados"], fala["horas_concluidas"]) == (1, 1.0)
    assert len(_tabela(banco, "uso_por_dia_e_programa", "dia")) == 2


def test_o_evento_repetido_vale_uma_vez(banco: sqlite3.Connection) -> None:
    _evento(
        banco, "e1", "login", "2026-11-01T12:00:01+00:00", "ana"
    )  # mesmo id do login
    _resumir(banco)

    ana = _tabela(banco, "uso_por_dia_e_usuario", "dia, quem_id")[0]

    assert ana["acessos"] == 2


def test_o_job_reprocessado_conta_uma_vez_por_estado_final(
    banco: sqlite3.Connection,
) -> None:
    # v1 é reprocessado e conclui de novo; v2 é reprocessado e agora conclui.
    _evento(
        banco,
        "e20",
        "fim_de_processamento",
        "2026-11-01T20:00:00+00:00",
        "ana",
        job_id="v1",
        programa="Hoje",
        estado="concluido",
    )
    _evento(
        banco,
        "e21",
        "fim_de_processamento",
        "2026-11-01T20:00:00+00:00",
        "ana",
        job_id="v2",
        programa="Hoje",
        estado="concluido",
    )
    banco.execute("INSERT INTO momentos VALUES ('v2', ?)", [HORA_MS // 2])
    _resumir(banco)

    ana = _tabela(banco, "uso_por_dia_e_usuario", "dia, quem_id")[0]

    assert ana["videos_concluidos"] == 2  # v1 uma vez só, e v2
    assert ana["videos_falhos"] == 1
    assert ana["horas_concluidas"] == 2.5


def test_rodar_de_novo_refaz_as_tabelas_sem_somar_em_dobro(
    banco: sqlite3.Connection,
) -> None:
    _resumir(banco)
    antes = _tabela(banco, "uso_por_dia", "dia")
    banco.execute(
        "DROP TABLE eventos"
    )  # a tabela temporária de uma rodada não vive na outra

    _resumir(banco)

    assert _tabela(banco, "uso_por_dia", "dia") == antes


def test_sem_eventos_as_tabelas_ficam_vazias() -> None:
    banco = _banco()

    _resumir(banco)

    for nome in re.findall(r"CREATE OR REPLACE TABLE `\$\{prefixo\}(\w+)`", SQL):
        assert banco.execute(f"SELECT COUNT(*) FROM {nome}").fetchone() == (0,)


def test_o_terraform_agenda_o_sql_com_a_conta_dos_resumos() -> None:
    assert 'resource "google_bigquery_data_transfer_config" "resumos_de_uso"' in TF
    assert 'data_source_id       = "scheduled_query"' in TF
    assert 'templatefile("${path.module}/resumos_de_uso.sql"' in TF
    assert "service_account_name = google_service_account.resumos_de_uso.email" in TF
    assert "roles/bigquery.jobUser" in TF
    assert "roles/bigquery.dataEditor" in TF
    assert "google_bigquery_dataset_iam_member" in TF
    assert "google_project_iam_member" in TF and "roles/bigquery.admin" not in TF


def test_as_tabelas_do_terraform_sao_as_que_o_sql_cria() -> None:
    criadas = re.findall(r"CREATE OR REPLACE TABLE `\$\{prefixo\}(\w+)`", SQL)
    listadas = re.search(r"resumos_de_uso = \[(.*?)\]", TF, re.DOTALL)
    assert listadas is not None

    assert criadas == re.findall(r'"(\w+)"', listadas.group(1))


def test_o_sql_le_as_tabelas_pelos_nomes_que_o_terraform_monta() -> None:
    assert "google_bigquery_table.eventos_de_uso.table_id" in TF
    assert "google_bigquery_table.momentos.table_id" in TF
    assert "eventos_de_uso`" not in SQL and "momentos`" not in SQL


def test_a_api_do_data_transfer_esta_ligada() -> None:
    assert "bigquerydatatransfer.googleapis.com" in (MODULO / "main.tf").read_text()


def test_a_web_recebe_so_tabelas_que_o_sql_cria() -> None:
    criadas = re.findall(r"CREATE OR REPLACE TABLE `\$\{prefixo\}(\w+)`", SQL)
    da_web = re.search(r"tabelas_do_painel_na_web = \{(.*?)\}", TF, re.DOTALL)
    assert da_web is not None

    assert set(re.findall(r'"(\w+)"', da_web.group(1))) <= set(criadas)
    principal = (MODULO / "main.tf").read_text()
    for nome in ("POR_DIA_E_USUARIO", "POR_DIA_E_PROGRAMA"):
        assert f'"PAINEL_TABELA_{nome}"' in principal
