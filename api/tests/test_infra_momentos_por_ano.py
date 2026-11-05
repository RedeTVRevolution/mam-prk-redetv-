"""Tabela de momentos dividida por ano, não por dia (#356)."""

import re
from pathlib import Path

MODULO = Path(__file__).resolve().parents[2] / "infra" / "modulos" / "mam"
TF = "\n".join(p.read_text() for p in sorted(MODULO.glob("*.tf")))


def _bloco(cabecalho: str) -> str:
    inicio = re.search(rf"^{re.escape(cabecalho)}", TF, re.MULTILINE)
    assert inicio
    return TF[inicio.start() : TF.index("\n}\n", inicio.start())]


def test_a_tabela_em_uso_e_dividida_por_ano_em_data_de_exibicao() -> None:
    bloco = _bloco('resource "google_bigquery_table" "momentos_por_ano"')
    assert re.search(r'type\s*=\s*"YEAR"', bloco)
    assert re.search(r'field\s*=\s*"data_de_exibicao"', bloco)
    assert re.search(r'clustering\s*=\s*\["programa",\s*"job_id"\]', bloco)
    assert "local.esquema_dos_momentos" in bloco
    assert "table_id" in bloco and "local.tabela_de_momentos" in bloco


def test_o_nome_em_uso_aponta_para_a_nova_e_a_antiga_fica_a_parte() -> None:
    assert re.search(
        r'^\s*tabela_de_momentos\s*=\s*"momentos_por_ano"', TF, re.MULTILINE
    )
    # A antiga sai do código depois da cópia (passo humano no infra/README.md).
    cabecalho = 'resource "google_bigquery_table" "momentos" '
    if cabecalho in TF:
        assert "local.tabela_de_momentos" not in _bloco(cabecalho)


def test_servicos_jobs_e_output_usam_a_tabela_nova() -> None:
    usos = re.findall(r'name\s*=\s*"BIGQUERY_TABELA"\s*value\s*=\s*([\w.]+)', TF)
    assert usos and set(usos) == {"local.tabela_de_momentos"}
    saida = _bloco('output "bigquery_tabela"')
    assert "local.tabela_de_momentos" in saida
