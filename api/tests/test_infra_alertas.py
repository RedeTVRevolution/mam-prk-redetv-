"""As métricas de log e os alertas dos sinais de qualidade no Terraform (#286), sem nuvem."""

import re
from pathlib import Path

from api.avaliacao import Queda
from api.decupagem import Decupagem
from api.sinais import (
    ContagemDaAnalise,
    registro_da_falha_de_etapa,
    registro_do_video_concluido,
)
from api.tests.test_decupagem import decupagem_valida

TF = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()

# O campo que cada métrica extrai do log do vídeo concluído.
CAMPOS = ("pct_escalonadas", "pct_nao_identificadas", "respostas_fora_do_esquema")


def _bloco(cabecalho: str) -> str:
    inicio = TF.index(cabecalho)
    return TF[inicio : TF.index("\n}\n", inicio)]


def test_cada_metrica_extrai_um_campo_que_o_log_do_video_concluido_traz() -> None:
    linha = registro_do_video_concluido(
        "j", "p", Decupagem.model_validate(decupagem_valida()), ContagemDaAnalise()
    )
    for campo in CAMPOS:
        assert f'"{campo}"' in linha
        assert f'"{campo}"' in TF or f"jsonPayload.{campo}" in TF


def test_o_filtro_de_cada_sinal_casa_o_evento_que_o_codigo_loga() -> None:
    assert '"evento": "video_concluido"' in registro_do_video_concluido(
        "j", None, Decupagem.model_validate(decupagem_valida()), ContagemDaAnalise()
    )
    assert 'jsonPayload.evento=\\"video_concluido\\"' in TF
    assert "falha_de_etapa" in registro_da_falha_de_etapa("analise", "j", "m")
    assert 'jsonPayload.evento=\\"falha_de_etapa\\"' in TF
    assert Queda(requisito="r", media=1, motivo="queda_na_semana", limiar=2)
    assert 'jsonPayload.evento=\\"queda_de_qualidade\\"' in TF


def test_a_falha_por_etapa_vira_um_rotulo_da_metrica() -> None:
    metrica = _bloco('resource "google_logging_metric" "falhas_por_etapa"')
    assert "EXTRACT(jsonPayload.etapa)" in metrica
    politica = _bloco('resource "google_monitoring_alert_policy" "falhas_por_etapa"')
    assert "metric.label.etapa" in politica


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
    assert len(novas) >= 5
    for nome in novas:
        bloco = _bloco(f'resource "google_monitoring_alert_policy" "{nome}"')
        assert "notification_channels = local.canais_de_alerta" in bloco
    assert (
        "canais_de_alerta     = [for canal in "
        "google_monitoring_notification_channel.admin_emergencia : canal.id]"
    ) in TF
