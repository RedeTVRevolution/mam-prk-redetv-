"""Os painéis de observabilidade no Terraform (#288): o contrato com os logs, sem nuvem."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from api.fila_job import amostrar_a_fila
from api.jobs import RepositorioEmMemoria
from api.sinais import registro_do_uso_do_modelo

INFRA = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
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
    assert 'toset(["tokens_de_entrada", "tokens_de_saida"])' in metrica
    assert "tokens_de_entrada" in linha and "tokens_de_saida" in linha
    assert 'REGEXP_EXTRACT(resource.labels.job_name, \\"^mam-(.+)$\\")' in metrica
    assert "EXTRACT(jsonPayload.modelo)" in metrica


def test_cada_metrica_lida_pelos_paineis_esta_declarada_com_esse_nome() -> None:
    lidas = re.search(r"metrica_de_log\s+= \{ for nome in \[(.*?)\]", TF)
    assert lidas
    declaradas = set(re.findall(r'name\s+= "mam_(\w+)"', TF))
    # As que nascem de um `for_each` com `name = "mam_${each.key}"`: a chave é o nome.
    tokens = _bloco('resource "google_logging_metric" "tokens_do_modelo"')
    fila = _bloco('resource "google_logging_metric" "fila"')
    por_chave = set(re.findall(r'"(\w+)"', tokens.split("toset(")[1].split(")")[0]))
    por_chave |= set(re.findall(r"^\s+(\w+)\s+= \{ extrai", fila, re.MULTILINE))
    assert por_chave == {
        "tokens_de_entrada",
        "tokens_de_saida",
        "fila_quantidade",
        "fila_idade",
    }
    for nome in re.findall(r'"(\w+)"', lidas.group(1)):
        assert nome in declaradas | por_chave, nome


def test_o_custo_le_a_soma_dos_tokens_da_distribuicao() -> None:
    custo = TF[TF.index("  custo_por_etapa = {") : TF.index("  graficos_dos_paineis")]
    assert "increase(${metrica}_sum{modelo=" in custo


def test_o_custo_usa_o_preco_da_configuracao_e_some_sem_preco() -> None:
    variavel = _bloco('variable "precos_por_milhao_de_tokens"')
    assert "default = {}" in variavel and "description" in variavel
    assert "var.precos_por_milhao_de_tokens" in TF
    assert "length(var.precos_por_milhao_de_tokens) == 0 ? []" in TF


def test_a_fila_loga_o_que_as_metricas_extraem() -> None:
    metrica = _bloco('resource "google_logging_metric" "fila"')
    assert 'jsonPayload.evento=\\"fila_de_jobs\\"' in metrica
    linhas: list[str] = []
    amostrar_a_fila(RepositorioEmMemoria(), datetime.now(UTC), linhas.append)
    linha = json.loads(linhas[0])
    assert linha["evento"] == "fila_de_jobs"
    for campo in ("quantidade", "idade_do_mais_antigo_s"):
        assert campo in linha and f'extrai = "{campo}"' in metrica
    assert "estado" in linha and "EXTRACT(jsonPayload.estado)" in metrica
    job = _bloco('resource "google_cloud_run_v2_job" "fila"')
    assert "api.fila_job" in job
    assert 'google_service_account.mam["fila"]' in job
    agenda = _bloco('resource "google_cloud_scheduler_job" "fila"')
    assert "var.agenda_da_fila" in agenda


def test_a_fila_e_amostrada_a_cada_5_min_e_o_painel_pega_mais_de_2_amostras() -> None:
    variavel = _bloco('variable "agenda_da_fila"')
    assert re.search(r'default\s+= "\*/5 \* \* \* \*"', variavel)
    painel = TF[TF.index("    fila = [\n") :]
    painel = painel[: painel.index("\n    ]\n")]
    janelas = re.findall(r"\[(\d+)m\]", painel)
    assert len(janelas) == 4
    # Com 10 min cabem só ~2 amostras e a média fica com buracos (0/0) (#344).
    assert all(int(j) > 2 * 5 for j in janelas)
    assert len(set(janelas)) == 1


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


def test_a_rota_da_api_e_so_o_recurso_de_v1_sem_o_front_nem_ids() -> None:
    metrica = _bloco('resource "google_logging_metric" "requisicoes_da_api"')
    assert "filter      = local.filtro_das_requisicoes_da_api" in metrica
    assert '/v1/\\""' in TF[TF.index("  filtro_das_requisicoes_da_api") :]
    assert (
        'REGEXP_EXTRACT(httpRequest.requestUrl, \\"^https?://[^/]+(/v1/[^/?]+)\\")'
        in metrica
    )
    assert "EXTRACT(httpRequest.status)" in metrica
