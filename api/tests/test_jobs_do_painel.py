"""A tabela dos Jobs do painel (#454): a consulta agendada roda no SQLite sobre eventos de
uso montados à mão; a carga dos Jobs antigos e o Terraform da tabela."""

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from api.eventos_de_uso import EventoDeUso
from api.jobs import Job, RepositorioEmMemoria
from api.jobs_do_painel import (
    ConfigDaTabelaDeJobs,
    LinhaDoJob,
    TabelaBigQuery,
    TabelaEmMemoria,
    linha_do_job,
    preencher,
)

MODULO = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
SQL = (MODULO / "jobs_do_painel.sql").read_text()
TF = (MODULO / "jobs_do_painel.tf").read_text()
COLUNAS_DA_TABELA = [
    "id",
    "programa",
    "duracao_ms",
    "quem_tipo",
    "quem_id",
    "estado",
    "criado_em",
    "concluido_em",
    "atualizado_em",
]


def _banco() -> sqlite3.Connection:
    banco = sqlite3.connect(":memory:")
    banco.execute(
        f"CREATE TABLE eventos_de_uso ({', '.join(EventoDeUso.model_fields)})"
    )
    banco.execute(f"CREATE TABLE jobs_do_painel ({', '.join(COLUNAS_DA_TABELA)})")
    return banco


def _evento(
    banco: sqlite3.Connection, id: str, tipo: str, quando: str, **resto: Any
) -> None:
    linha = {
        "id": id,
        "tipo": tipo,
        "quando": quando,
        "quem_tipo": "usuario",
        "quem_id": "ana",
        **resto,
    }
    banco.execute(
        f"INSERT INTO eventos_de_uso ({', '.join(linha)}) "
        f"VALUES ({', '.join('?' * len(linha))})",
        list(linha.values()),
    )


def _rodar(
    banco: sqlite3.Connection, inicio: str = "'2000-01-01T00:00:00+00:00'"
) -> None:
    sql = (
        SQL.replace("${tabela}", "jobs_do_painel")
        .replace("${tabela_de_eventos}", "eventos_de_uso")
        .replace("${inicio_da_janela}", inicio)
    )
    for (nome,) in banco.execute(
        "SELECT name FROM sqlite_temp_master WHERE name IN "
        "('janela', 'do_envio', 'do_fim', 'novos')"
    ).fetchall():
        banco.execute(f"DROP TABLE {nome}")
    banco.executescript(sql)


def _linhas(banco: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    cursor = banco.execute("SELECT * FROM jobs_do_painel ORDER BY id")
    nomes = [c[0] for c in cursor.description]
    return {r[0]: dict(zip(nomes, r, strict=True)) for r in cursor.fetchall()}


def test_o_job_criado_chega_com_programa_dono_e_data() -> None:
    b = _banco()
    _evento(b, "e1", "envio", "2026-11-01T12:00:00+00:00", job_id="v1", programa="Hoje")
    _rodar(b)

    assert _linhas(b)["v1"] == {
        "id": "v1",
        "programa": "Hoje",
        "duracao_ms": None,
        "quem_tipo": "usuario",
        "quem_id": "ana",
        "estado": "em_andamento",
        "criado_em": "2026-11-01T12:00:00+00:00",
        "concluido_em": None,
        "atualizado_em": "2026-11-01T12:00:00+00:00",
    }


def test_a_consulta_nao_recria_o_purgado_nem_com_fim_atrasado() -> None:
    b = _banco()
    _evento(b, "e1", "envio", "2026-11-01T12:00:00+00:00", job_id="v1")
    _evento(b, "e2", "envio", "2026-11-01T12:00:00+00:00", job_id="v2")
    _rodar(b)
    b.execute("DELETE FROM jobs_do_painel WHERE id = 'v1'")
    _evento(b, "p1", "purga", "2026-11-01T12:01:00+00:00", job_id="v1")
    _rodar(b)
    assert set(_linhas(b)) == {"v2"}

    _evento(
        b, "f1", "fim_de_processamento", "2026-11-05T12:00:00+00:00",
        job_id="v1", estado="concluido",
    )  # fmt: skip
    _rodar(b, "'2026-11-04T00:00:00+00:00'")
    _rodar(b, "'2026-11-04T00:00:00+00:00'")
    assert set(_linhas(b)) == {"v2"}


def test_o_job_concluido_traz_estado_duracao_e_dia_do_fim() -> None:
    b = _banco()
    _evento(b, "e1", "envio", "2026-11-01T12:00:00+00:00", job_id="v1", programa="Hoje")
    _evento(
        b,
        "e2",
        "fim_de_processamento",
        "2026-11-01T13:00:00+00:00",
        job_id="v1",
        programa="Hoje",
        estado="concluido",
        duracao_do_video_ms=7_200_000,
    )
    _rodar(b)

    linha = _linhas(b)["v1"]
    assert linha["estado"] == "concluido"
    assert linha["duracao_ms"] == 7_200_000
    assert linha["criado_em"] == "2026-11-01T12:00:00+00:00"
    assert linha["concluido_em"] == "2026-11-01T13:00:00+00:00"
    assert linha["atualizado_em"] == "2026-11-01T13:00:00+00:00"


def test_o_job_de_sistema_tem_o_sistema_como_dono() -> None:
    b = _banco()
    _evento(
        b, "e1", "envio", "2026-11-01T12:00:00+00:00",
        quem_tipo="sistema", quem_id="cms", job_id="v1",
    )  # fmt: skip
    _rodar(b)

    assert (_linhas(b)["v1"]["quem_tipo"], _linhas(b)["v1"]["quem_id"]) == (
        "sistema",
        "cms",
    )


def test_o_reprocessado_troca_o_fim_e_mantem_criacao_e_dono() -> None:
    b = _banco()
    _evento(b, "e1", "envio", "2026-11-01T12:00:00+00:00", job_id="v1", programa="Hoje")
    _evento(
        b, "e2", "fim_de_processamento", "2026-11-01T13:00:00+00:00",
        job_id="v1", estado="falhou", codigo_falha="analise_falhou",
    )  # fmt: skip
    _rodar(b)
    assert _linhas(b)["v1"]["estado"] == "falhou"
    assert _linhas(b)["v1"]["duracao_ms"] is None

    # Dias depois, fora da janela do envio: só o fim novo está nela.
    _evento(
        b, "e3", "fim_de_processamento", "2026-11-05T09:00:00+00:00",
        job_id="v1", estado="concluido", duracao_do_video_ms=3_600_000,
    )  # fmt: skip
    _rodar(b, "'2026-11-04T00:00:00+00:00'")

    linha = _linhas(b)["v1"]
    assert len(_linhas(b)) == 1
    assert linha["estado"] == "concluido"
    assert linha["duracao_ms"] == 3_600_000
    assert linha["programa"] == "Hoje"
    assert linha["quem_id"] == "ana"
    assert linha["criado_em"] == "2026-11-01T12:00:00+00:00"
    assert linha["concluido_em"] == "2026-11-05T09:00:00+00:00"


def test_o_fim_sem_duracao_nao_apaga_a_que_ja_havia() -> None:
    b = _banco()
    _evento(b, "e1", "envio", "2026-11-01T12:00:00+00:00", job_id="v1")
    _evento(
        b, "e2", "fim_de_processamento", "2026-11-01T13:00:00+00:00",
        job_id="v1", estado="concluido", duracao_do_video_ms=1000,
    )  # fmt: skip
    _rodar(b)
    _evento(
        b, "e3", "fim_de_processamento", "2026-11-05T09:00:00+00:00",
        job_id="v1", estado="falhou",
    )  # fmt: skip
    _rodar(b, "'2026-11-04T00:00:00+00:00'")

    assert _linhas(b)["v1"]["duracao_ms"] == 1000
    assert _linhas(b)["v1"]["estado"] == "falhou"


def test_rodar_de_novo_e_o_evento_repetido_dao_o_mesmo() -> None:
    b = _banco()
    _evento(b, "e1", "envio", "2026-11-01T12:00:00+00:00", job_id="v1")
    _evento(b, "e1", "envio", "2026-11-01T12:00:00+00:00", job_id="v1")
    _evento(
        b, "e2", "fim_de_processamento", "2026-11-01T13:00:00+00:00",
        job_id="v1", estado="concluido",
    )  # fmt: skip
    _rodar(b)
    antes = _linhas(b)
    _rodar(b)

    assert _linhas(b) == antes
    assert b.execute("SELECT COUNT(*) FROM jobs_do_painel").fetchone() == (1,)


def test_job_que_nao_teve_evento_na_janela_fica_como_esta() -> None:
    b = _banco()
    b.execute(
        "INSERT INTO jobs_do_painel VALUES "
        "('antigo', 'Hoje', 10, 'usuario', 'bia', 'concluido', 'a', 'b', 'c')"
    )
    _evento(b, "e1", "envio", "2026-11-01T12:00:00+00:00", job_id="v1")
    _rodar(b)

    assert set(_linhas(b)) == {"antigo", "v1"}
    assert _linhas(b)["antigo"]["quem_id"] == "bia"


def test_so_envio_e_fim_entram_e_a_janela_corta() -> None:
    b = _banco()
    _evento(b, "e1", "busca", "2026-11-01T12:00:00+00:00", job_id="v1")
    _evento(b, "e2", "correcao", "2026-11-01T12:00:00+00:00", job_id="v1")
    _evento(b, "e3", "envio", "2026-10-01T12:00:00+00:00", job_id="velho")
    _rodar(b, "'2026-11-01T00:00:00+00:00'")

    assert _linhas(b) == {}


def test_as_colunas_da_tabela_do_terraform_sao_as_do_sql() -> None:
    nomes = re.findall(r'^    \{ name = "(\w+)"', TF, re.MULTILINE)

    assert nomes == COLUNAS_DA_TABELA


def test_a_tabela_e_particionada_por_dia_e_agrupada_por_programa() -> None:
    bloco = TF[TF.index('resource "google_bigquery_table" "jobs_do_painel"') :]
    bloco = bloco[: bloco.index("\n}\n")]

    assert re.search(r'type\s*=\s*"DAY"', bloco)
    assert re.search(r'field\s*=\s*"criado_em"', bloco)
    assert re.search(r'clustering\s*=\s*\["programa",\s*"id"\]', bloco)
    assert "deletion_protection = true" in bloco
    assert "local.tabela_de_jobs_do_painel" in bloco


def test_a_consulta_agendada_usa_a_conta_dos_resumos_e_o_nome_vem_do_terraform() -> (
    None
):
    assert "google_service_account.resumos_de_uso.email" in TF
    assert 'templatefile("${path.module}/jobs_do_painel.sql"' in TF
    assert 'output "bigquery_tabela_de_jobs"' in TF


def test_as_duas_consultas_agendadas_do_painel_rodam_de_hora_em_hora_na_mesma_janela() -> None:
    resumos = (MODULO / "resumos_de_uso.tf").read_text()
    for tf in (TF, resumos):
        assert 'schedule             = "every 1 hours"' in tf
        assert "local.janela_dos_resumos_em_dias - 1" in tf
    assert "janela_dos_resumos_em_dias = 2" in resumos


def _job(**mudancas: Any) -> Job:
    base: dict[str, Any] = {
        "id": "v1",
        "nome": "a.mp4",
        "tamanho_bytes": 10,
        "estado": "concluido",
        "criado_por": "ana",
        "programa": "Hoje",
        "duracao_s": 7200.5,
        "criado_em": datetime(2026, 11, 1, 12, tzinfo=UTC),
        "atualizado_em": datetime(2026, 11, 1, 13, tzinfo=UTC),
    }
    return Job(**{**base, **mudancas})


def test_a_linha_do_job_concluido_de_usuario() -> None:
    assert linha_do_job(_job()) == LinhaDoJob(
        id="v1",
        programa="Hoje",
        duracao_ms=7_200_500,
        quem_tipo="usuario",
        quem_id="ana",
        estado="concluido",
        criado_em=datetime(2026, 11, 1, 12, tzinfo=UTC),
        concluido_em=datetime(2026, 11, 1, 13, tzinfo=UTC),
        atualizado_em=datetime(2026, 11, 1, 13, tzinfo=UTC),
    )


def test_a_linha_do_job_de_sistema_em_andamento_nao_tem_conclusao() -> None:
    linha = linha_do_job(_job(sistema="cms", estado="analisando", duracao_s=None))

    assert (linha.quem_tipo, linha.quem_id) == ("sistema", "cms")
    assert linha.estado == "em_andamento"
    assert linha.concluido_em is None
    assert linha.duracao_ms is None


def test_a_linha_do_job_cancelado_fecha_com_o_estado_dele() -> None:
    linha = linha_do_job(_job(estado="cancelado"))

    assert linha.estado == "cancelado"
    assert linha.concluido_em == linha.atualizado_em


class _TabelaQueContaLotes(TabelaEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.lotes: list[int] = []

    def gravar(self, linhas: list[LinhaDoJob]) -> None:
        self.lotes.append(len(linhas))
        super().gravar(linhas)


def test_o_preenchimento_grava_todos_os_jobs_em_lotes_e_repetir_nao_duplica() -> None:
    repositorio = RepositorioEmMemoria()
    for i in range(5):
        repositorio.salvar(_job(id=f"v{i}"))
    tabela = _TabelaQueContaLotes()
    assert preencher(repositorio, tabela, por_lote=2) == 5
    assert preencher(repositorio, tabela, por_lote=2) == 5

    assert tabela.lotes == [2, 2, 1, 2, 2, 1]
    assert sorted(tabela.por_id) == [f"v{i}" for i in range(5)]


def test_o_merge_do_bigquery_atualiza_pelo_id_e_leva_as_linhas_como_json() -> None:
    corpos: list[dict[str, Any]] = []

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        corpos.append(corpo)
        return {"jobComplete": True}

    config = ConfigDaTabelaDeJobs("p", "d", "t", "r")
    TabelaBigQuery(config, transporte).gravar([linha_do_job(_job())])

    consulta = corpos[0]["query"]
    assert "MERGE `p.d.t`" in consulta
    assert "ON t.id = s.id" in consulta
    assert "WHEN MATCHED THEN UPDATE" in consulta
    assert corpos[0]["location"] == "r"
    assert '"id": "v1"' in corpos[0]["queryParameters"][0]["parameterValue"]["value"]


def test_o_merge_que_nao_termina_no_prazo_falha() -> None:
    config = ConfigDaTabelaDeJobs("p", "d", "t", "r")
    tabela = TabelaBigQuery(config, lambda corpo: {"jobComplete": False})

    with pytest.raises(RuntimeError):
        tabela.gravar([linha_do_job(_job())])
