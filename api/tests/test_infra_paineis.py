"""Os painéis de observabilidade no Terraform (#288): o contrato com os logs, sem nuvem."""

import json
import re
from pathlib import Path

from api.sinais import registro_do_uso_do_modelo

INFRA = Path(__file__).parents[2] / "infra"
TF = (INFRA / "main.tf").read_text()
WORKFLOW = (INFRA / "validacao.workflow.yaml").read_text()


def _bloco(cabecalho: str) -> str:
    inicio = TF.index(cabecalho)
    return TF[inicio : TF.index("\n}\n", inicio)]


def test_o_tempo_da_etapa_vem_do_marca_fim_so_das_etapas_concluidas() -> None:
    marca_fim = WORKFLOW[
        WORKFLOW.index("\nmarca_fim:") : WORKFLOW.index("\netapa_com_gpu:")
    ]
    log = marca_fim[marca_fim.index("registra_a_duracao_da_etapa:") :]
    assert 'condition: $${resultado == "concluida"}' in log
    assert "evento: duracao_da_etapa" in log and "duracao_s:" in log
    assert log.index("duracao_s:") < log.index("grava_o_fim:")
    metrica = _bloco('resource "google_logging_metric" "duracao_da_etapa"')
    assert 'jsonPayload.evento=\\"duracao_da_etapa\\"' in metrica
    assert "EXTRACT(jsonPayload.duracao_s)" in metrica
    assert "EXTRACT(jsonPayload.etapa)" in metrica


def test_os_tokens_saem_do_log_de_uso_com_a_etapa_do_job_e_o_modelo() -> None:
    linha = json.loads(registro_do_uso_do_modelo("m", 1, 2))
    metrica = _bloco('resource "google_logging_metric" "tokens_do_modelo"')
    assert f'jsonPayload.evento=\\"{linha["evento"]}\\"' in metrica
    for campo in ("tokens_de_entrada", "tokens_de_saida"):
        assert campo in linha and f'= "{campo}"' in metrica
    assert "EXTRACT(resource.labels.job_name)" in metrica
    assert "EXTRACT(jsonPayload.modelo)" in metrica


def test_cada_metrica_lida_pelos_paineis_esta_declarada_com_esse_nome() -> None:
    lidas = re.search(r"metrica_de_log\s+= \{ for nome in \[(.*?)\]", TF)
    assert lidas
    declaradas = set(re.findall(r'name\s+= "mam_(\w+)"', TF))
    # As que nascem de um `for_each` com `name = "mam_${each.key}"`: a chave é o nome.
    por_chave = set(re.findall(r'^\s+(\w+)\s+= (?:"\w+"|\{ extrai)', TF, re.MULTILINE))
    for nome in re.findall(r'"(\w+)"', lidas.group(1)):
        assert nome in declaradas | por_chave, nome


def test_o_custo_usa_o_preco_da_configuracao_e_some_sem_preco() -> None:
    variavel = _bloco('variable "precos_por_milhao_de_tokens"')
    assert "default = {}" in variavel and "description" in variavel
    assert "var.precos_por_milhao_de_tokens" in TF
    assert "length(var.precos_por_milhao_de_tokens) == 0 ? []" in TF


def test_a_fila_loga_o_que_as_metricas_extraem() -> None:
    metrica = _bloco('resource "google_logging_metric" "fila"')
    assert 'jsonPayload.evento=\\"fila_de_jobs\\"' in metrica
    for campo in ("quantidade", "idade_do_mais_antigo_s", "estado"):
        assert f"jsonPayload.{campo}" in metrica or f'"{campo}"' in metrica
    job = _bloco('resource "google_cloud_run_v2_job" "fila"')
    assert "api.fila_job" in job
    assert 'google_service_account.mam["fila"]' in job
    agenda = _bloco('resource "google_cloud_scheduler_job" "fila"')
    assert "var.agenda_da_fila" in agenda


def test_a_falta_de_gpu_e_logada_so_quando_falta_gpu_ou_cota() -> None:
    gpu = WORKFLOW[WORKFLOW.index("\nroda_o_job_com_gpu:") :]
    assert gpu.index("not faltou_gpu") < gpu.index("evento: falta_de_gpu")
    assert gpu.index("evento: falta_de_gpu") < gpu.index("ainda_cabe_esperar:")
    metrica = _bloco('resource "google_logging_metric" "falta_de_gpu"')
    assert 'jsonPayload.evento=\\"falta_de_gpu\\"' in metrica


def test_os_quatro_paineis_existem_e_o_da_gpu_cobre_os_tres_jobs_com_gpu() -> None:
    for chave in ("tempo_e_custo", "fila", "erros_da_api", "gpu"):
        assert re.search(rf"^\s+{chave}\s+= ", TF, re.MULTILINE)
    assert 'resource "google_monitoring_dashboard" "painel"' in TF
    for job in ("transcricao_gpu", "ocr_gpu", "objetos_gpu"):
        assert f"google_cloud_run_v2_job.{job}.name" in _bloco(
            "locals {\n  janela_dos_paineis"
        )


def test_a_rota_da_api_nao_leva_ids_do_caminho() -> None:
    metrica = _bloco('resource "google_logging_metric" "requisicoes_da_api"')
    assert "REGEXP_EXTRACT(httpRequest.requestUrl" in metrica
    assert "EXTRACT(httpRequest.status)" in metrica
