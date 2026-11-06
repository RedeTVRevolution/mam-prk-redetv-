"""As métricas de log e os alertas dos sinais de qualidade no Terraform (#286), sem nuvem."""

import json
import re
from pathlib import Path

from api.decupagem import Decupagem
from api.sinais import (
    ContagemDaAnalise,
    registro_da_falha_de_etapa,
    registro_da_resposta_fora_do_esquema,
    registro_do_video_concluido,
)
from api.sinal_do_programa import Desvio, Referencia, registro_do_desvio
from api.tests.test_decupagem import decupagem_valida

INFRA = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
TF = (INFRA / "main.tf").read_text()
WORKFLOW = (INFRA / "validacao.workflow.yaml").read_text()


def _bloco(cabecalho: str) -> str:
    inicio = TF.index(cabecalho)
    return TF[inicio : TF.index("\n}\n", inicio)]


def test_cada_percentual_extraido_e_um_campo_que_o_log_do_video_concluido_traz() -> (
    None
):
    linha = json.loads(
        registro_do_video_concluido(
            "j", "p", Decupagem.model_validate(decupagem_valida()), ContagemDaAnalise()
        )
    )
    metrica = _bloco('resource "google_logging_metric" "sinal_percentual"')
    assert "EXTRACT(jsonPayload.${each.value.campo})" in metrica
    campos = re.findall(r'campo\s+= "(\w+)"', TF)
    assert campos == ["pct_nao_identificadas"]
    for campo in campos:
        assert isinstance(linha[campo], float)


def test_respostas_fora_do_esquema_sao_contadas_por_linha_sem_extrator() -> None:
    registro = json.loads(registro_da_resposta_fora_do_esquema("m", "x"))
    metrica = _bloco('resource "google_logging_metric" "respostas_fora_do_esquema"')
    assert f'jsonPayload.evento=\\"{registro["evento"]}\\"' in metrica
    assert "value_extractor" not in metrica
    assert 'value_type  = "INT64"' in metrica


def test_o_filtro_de_cada_sinal_casa_o_evento_que_o_codigo_loga() -> None:
    assert '"evento": "video_concluido"' in registro_do_video_concluido(
        "j", None, Decupagem.model_validate(decupagem_valida()), ContagemDaAnalise()
    )
    assert 'jsonPayload.evento=\\"video_concluido\\"' in TF
    assert "falha_de_etapa" in registro_da_falha_de_etapa("analise", "j", "m")
    assert 'jsonPayload.evento=\\"falha_de_etapa\\"' in TF


def test_a_falha_por_etapa_vira_um_rotulo_da_metrica() -> None:
    metrica = _bloco('resource "google_logging_metric" "falhas_por_etapa"')
    assert "EXTRACT(jsonPayload.etapa)" in metrica
    politica = _bloco('resource "google_monitoring_alert_policy" "falhas_por_etapa"')
    assert "metric.label.etapa" in politica


def test_a_execucao_que_falha_em_qualquer_etapa_loga_pelo_workflows() -> None:
    """Todas as etapas fecham pelo `marca_fim`; a falha da execução é logada ali, uma vez."""
    marca_fim = WORKFLOW[
        WORKFLOW.index("\nmarca_fim:") : WORKFLOW.index("\netapa_com_gpu:")
    ]
    assert "condition: $${not falhou_na_execucao}" in marca_fim
    log = marca_fim[marca_fim.index("registra_a_falha_da_etapa:") :]
    assert "evento: falha_de_etapa" in log and "etapa: $${etapa}" in log
    assert log.index("evento: falha_de_etapa") < log.index("- le_o_estado:")
    metrica = _bloco('resource "google_logging_metric" "falhas_por_etapa"')
    assert 'resource.type=\\"workflows.googleapis.com/Workflow\\"' in metrica
    politica = _bloco('resource "google_monitoring_alert_policy" "falhas_por_etapa"')
    # Uma condição por origem: só cloud_run_job perderia as falhas do Workflows.
    assert 'Jobs      = "cloud_run_job"' in politica
    assert 'Workflows = "workflows.googleapis.com/Workflow"' in politica
    assert 'resource.type=\\"${conditions.value}\\"' in politica


def test_os_limiares_sao_variaveis_com_descricao() -> None:
    for nome in (
        "limiar_de_nao_identificadas_pct",
        "limiar_de_fora_do_esquema",
        "limite_de_falhas_por_etapa",
        "janela_dos_alertas_horas",
    ):
        variavel = _bloco(f'variable "{nome}"')
        assert "description" in variavel and "default" in variavel
        assert f"var.{nome}" in TF


def test_todo_alerta_novo_usa_o_canal_de_emergencia() -> None:
    politicas = re.findall(r'resource "google_monitoring_alert_policy" "(\w+)"', TF)
    novas = [p for p in politicas if p != "login_admin_emergencia"]
    assert len(novas) >= 4
    for nome in novas:
        bloco = _bloco(f'resource "google_monitoring_alert_policy" "{nome}"')
        assert "notification_channels = local.canais_de_alerta" in bloco
    assert (
        "canais_de_alerta     = [for canal in "
        "google_monitoring_notification_channel.admin_emergencia : canal.id]"
    ) in TF


def test_o_alerta_do_sinal_por_programa_casa_o_log_e_os_rotulos() -> None:
    registro = json.loads(
        registro_do_desvio(
            "j", "Programa", Desvio("pautas", 9.0, Referencia(5, 3.0, 1.0)), 3
        )
    )
    metrica = _bloco('resource "google_logging_metric" "desvio_de_programa"')
    assert f'jsonPayload.evento=\\"{registro["evento"]}\\"' in metrica
    for rotulo in ("tipo", "programa"):
        assert registro[rotulo]
        assert f"EXTRACT(jsonPayload.{rotulo})" in metrica
    politica = _bloco('resource "google_monitoring_alert_policy" "desvio_de_programa"')
    assert "metric.label.programa" in politica and "metric.label.tipo" in politica


def test_o_job_de_indexacao_recebe_n_e_k_do_sinal_por_programa() -> None:
    indexacao = _bloco('resource "google_cloud_run_v2_job" "indexacao"')
    assert 'name  = "SINAL_VIDEOS"' in indexacao
    assert "var.videos_do_sinal_por_programa" in indexacao
    assert 'name  = "SINAL_DESVIOS"' in indexacao
    assert "var.desvios_do_sinal_por_programa" in indexacao


def test_todo_alerta_de_metrica_restringe_o_resource_type() -> None:
    # A API recusa a condição de alerta sem resource.type no filtro (deploy de 2026-11-03).
    filtros = re.findall(r'filter\s+= "(metric\.type=.*)"', TF)
    assert len(filtros) >= 4
    for filtro in filtros:
        assert "resource.type=" in filtro, filtro


def test_o_alerta_do_percentual_nao_usa_align_mean_na_distribuicao() -> None:
    # ALIGN_MEAN não se aplica a métrica DELTA de distribuição: a API recusa.
    alerta = _bloco('resource "google_monitoring_alert_policy" "sinal_percentual"')
    assert not re.search(r'per_series_aligner\s+= "ALIGN_MEAN"', alerta)
    assert 'cross_series_reducer = "REDUCE_MEAN"' in alerta
