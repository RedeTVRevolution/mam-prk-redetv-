"""Permissões e configuração das duas entradas da purga (#504)."""

import re

from api.tests.test_infra_eventos_de_uso import MAIN, MODULO, _bloco


def test_web_e_purga_recebem_as_tabelas_pela_configuracao() -> None:
    web = _bloco(MAIN, 'resource "google_cloud_run_v2_service" "web"')
    purga = (MODULO / "purga.tf").read_text()
    for bloco in (web, purga):
        for nome in (
            "BIGQUERY_DATASET",
            "BIGQUERY_REGIAO",
            "BIGQUERY_TABELA",
            "BIGQUERY_TABELA_ANTIGA",
            "BIGQUERY_TABELA_DE_JOBS",
            "BIGQUERY_TABELA_DE_REVISAO",
            "BIGQUERY_TABELA_DE_EVENTOS",
        ):
            assert f'"{nome}"' in bloco


def test_purga_pode_apagar_linhas_e_rodar_consultas() -> None:
    dataset = _bloco(
        MAIN, 'resource "google_bigquery_dataset_iam_member" "grava_momentos"'
    )
    assert '"purga"' in dataset
    assert '"roles/bigquery.dataEditor"' in dataset
    assert re.search(r'purga\s*=\s*\[[^\]]*"roles/bigquery.jobUser"', MAIN)


def test_consulta_agendada_le_o_marcador_sob_a_mesma_trava_da_purga() -> None:
    sql = (MODULO / "jobs_do_painel.sql").read_text()
    assert (
        sql.index("BEGIN TRANSACTION;")
        < sql.index("DELETE FROM `${tabela}` WHERE FALSE;")
        < sql.index("CREATE TEMP TABLE janela")
    )


def test_tabela_antiga_de_momentos_nao_existe_mais_no_codigo() -> None:
    """Etapa 2, apply 1 (#567): só o recurso sai; a variável e o IAM ficam até o apply 2."""
    assert 'resource "google_bigquery_table" "momentos"' not in MAIN
