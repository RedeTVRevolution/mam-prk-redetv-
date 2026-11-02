"""As métricas de log e os alertas dos sinais de qualidade no Terraform (#286), sem nuvem."""

import json
import re
from datetime import date
from pathlib import Path

from api.avaliacao import Queda, registro_da_queda
from api.decupagem import Decupagem
from api.sinais import (
    ContagemDaAnalise,
    registro_da_falha_de_etapa,
    registro_da_resposta_fora_do_esquema,
    registro_do_video_concluido,
)
from api.tests.test_decupagem import decupagem_valida

INFRA = Path(__file__).parents[2] / "infra"
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
    assert sorted(campos) == ["pct_escalonadas", "pct_nao_identificadas"]
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
    queda = json.loads(
        registro_da_queda(
            Queda(requisito="r", media=1, motivo="queda_na_semana", limiar=2),
            date(2026, 11, 1),
            {},
        )
    )
    assert queda["requisito"] == "r"
    metrica = _bloco('resource "google_logging_metric" "queda_da_avaliacao"')
    assert f'jsonPayload.evento=\\"{queda["evento"]}\\"' in metrica
    assert "EXTRACT(jsonPayload.requisito)" in metrica


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
    assert "cloud_run_job" not in politica


def test_os_limiares_sao_variaveis_com_descricao() -> None:
    for nome in (
        "limiar_de_escalonadas_pct",
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
