"""Definição do Workflows da validação: o comportamento real é conferido no #14."""

import re
from pathlib import Path

DEFINICAO = Path(__file__).parents[2] / "infra" / "validacao.workflow.yaml"


def _texto() -> str:
    return DEFINICAO.read_text()


def test_roda_o_job_com_override_de_job_id() -> None:
    texto = _texto()

    assert "googleapis.run.v2.projects.locations.jobs.run" in texto
    assert "name: JOB_ID" in texto
    assert "${job_id}" in texto


def test_falha_da_execucao_grava_falhou_com_arquivo_corrompido() -> None:
    texto = _texto()

    assert "try:" in texto and "except:" in texto
    # O `raise` repassa o erro da execução: sem `as: e`, a variável não existe.
    assert "as: e" in texto and "raise: $${e}" in texto
    assert "googleapis.firestore.v1.projects.databases.documents.patch" in texto
    assert "arquivo_corrompido" in texto
    assert "falhou" in texto


def test_roda_o_job_de_analise_so_se_o_job_esta_em_analisando() -> None:
    texto = _texto()

    leitura = texto.index("documents.get")
    condicao = texto.index('estado.stringValue == "analisando"')
    analisa = texto.index("- analisa:")
    assert leitura < condicao < analisa
    passo = texto[analisa:]
    assert "googleapis.run.v2.projects.locations.jobs.run" in passo
    assert "jobs/${job_de_analise}" in passo
    assert "name: JOB_ID" in passo and "value: $${job_id}" in passo
    # A análise não é mais uma chamada HTTP: o teto de 1800 s do Workflows não vale.
    assert "http.post" not in texto and "url_da_analise" not in texto
    # O conector espera mais que o timeout de 21600 s do Job, não o padrão de 1800 s.
    assert "timeout: 21900" in passo
    # Fora de `analisando` o fluxo pula a análise.
    assert "next: fim" in texto


def test_falha_da_analise_grava_analise_falhou() -> None:
    texto = _texto()

    depois = texto[texto.index("- analisa:") :]
    assert "except:" in depois and "as: e" in depois
    assert "stringValue: analise_falhou" in depois
    assert "stringValue: falhou" in depois
    assert "raise: $${e}" in depois


def test_falha_da_chamada_nao_sobrescreve_job_que_ja_saiu_de_analisando() -> None:
    texto = _texto()

    depois_da_chamada = texto[texto.index("- analisa:") :]
    releitura = depois_da_chamada.index("documents.get")
    condicao = depois_da_chamada.index('estado.stringValue != "analisando"')
    patch = depois_da_chamada.index("documents.patch")
    assert releitura < condicao < patch
    # O patch só vale se o documento não mudou desde a releitura.
    assert "updateTime: $${atual.updateTime}" in depois_da_chamada


def test_objeto_sem_job_nao_derruba_a_leitura() -> None:
    texto = _texto()

    leitura = texto[texto.index("le_o_job:") : texto.index("so_se_analisando:")]
    assert "e.code == 404" in leitura and "next: fim" in leitura


def test_falha_da_execucao_nao_sobrescreve_job_cancelado() -> None:
    texto = _texto()

    excecao = texto[texto.index("le_antes_de_marcar:") : texto.index("le_o_job:")]
    releitura = excecao.index("documents.get")
    condicao = excecao.index('estado.stringValue == "cancelado"')
    patch = excecao.index("documents.patch")
    assert releitura < condicao < patch
    # O patch só vale se o documento não mudou desde a releitura.
    assert "updateTime: $${antes.updateTime}" in excecao
    # Um objeto sem Job correspondente não cria documento: a releitura dá 404.
    assert "erro_da_leitura.code == 404" in excecao


def test_ordem_e_validacao_transcricao_analise() -> None:
    texto = _texto()

    valida = texto.index("- valida:")
    transcreve = texto.index("- transcreve:")
    analisa = texto.index("- analisa:")
    assert valida < transcreve < analisa
    assert "jobs/${job_de_validacao}" in texto
    assert "jobs/${job_de_transcricao}" in texto
    # A transcrição só roda com o Job em `analisando`.
    assert texto.index('estado.stringValue == "analisando"') < transcreve


def test_transcricao_roda_o_job_com_override_de_job_id() -> None:
    texto = _texto()

    passo = texto[texto.index("- transcreve:") : texto.index("- analisa:")]
    assert "googleapis.run.v2.projects.locations.jobs.run" in passo
    assert "jobs/${job_de_transcricao}" in passo
    assert "name: JOB_ID" in passo and "value: $${job_id}" in passo
    # O conector espera mais que o timeout de 21600 s do Job, não o padrão de 1800 s.
    assert "timeout: 21900" in passo


def test_falha_da_transcricao_grava_transcricao_falhou_sem_sobrescrever_outro_estado() -> (
    None
):
    texto = _texto()

    passo = texto[texto.index("- transcreve:") : texto.index("- analisa:")]
    releitura = passo.index("documents.get")
    condicao = passo.index('estado.stringValue != "analisando"')
    patch = passo.index("documents.patch")
    assert releitura < condicao < patch
    assert "updateTime: $${durante.updateTime}" in passo
    assert "stringValue: transcricao_falhou" in passo
    assert "raise: $${e}" in passo


def test_ocr_da_tela_roda_depois_da_transcricao_e_antes_da_analise() -> None:
    texto = _texto()

    transcreve = texto.index("- transcreve:")
    le_a_tela = texto.index("- le_a_tela:")
    analisa = texto.index("- analisa:")
    assert transcreve < le_a_tela < analisa
    passo = texto[le_a_tela:analisa]
    assert "googleapis.run.v2.projects.locations.jobs.run" in passo
    assert "jobs/${job_de_ocr}" in passo
    assert "name: JOB_ID" in passo and "value: $${job_id}" in passo
    assert "timeout: 29100" in passo


def test_falha_do_ocr_grava_ocr_falhou_sem_sobrescrever_outro_estado() -> None:
    texto = _texto()

    passo = texto[texto.index("- le_a_tela:") : texto.index("- analisa:")]
    releitura = passo.index("documents.get")
    condicao = passo.index('estado.stringValue != "analisando"')
    patch = passo.index("documents.patch")
    assert releitura < condicao < patch
    assert "updateTime: $${durante_o_ocr.updateTime}" in passo
    assert "stringValue: ocr_falhou" in passo
    assert "raise: $${e}" in passo


def test_job_de_ocr_no_main_tf_sem_internet_e_na_rede_da_validacao() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()

    job = main[main.index('resource "google_cloud_run_v2_job" "ocr"') :].split(
        "\nresource "
    )[0]
    assert "google_compute_network.validacao.id" in job
    assert "google_compute_subnetwork.validacao.id" in job
    assert "var.imagem_ocr" in job
    assert "max_retries     = 0" in job
    assert "external_ip" not in main and "google_compute_router_nat" not in main
    assert "job_de_ocr         = google_cloud_run_v2_job.ocr.name" in main


def test_job_de_analise_no_main_tf_e_o_que_o_workflow_roda() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()

    job = main[main.index('resource "google_cloud_run_v2_job" "analise"') :].split(
        "\nresource "
    )[0]
    assert 'args    = ["-m", "api.analise"]' in job
    assert "max_retries     = 0" in job
    assert "JANELAS_EM_PARALELO" in job and "var.janelas_em_paralelo" in job
    assert "job_de_analise     = google_cloud_run_v2_job.analise.name" in main
    assert "google_cloud_run_v2_service.analise" not in main
    # O Job de análise dura mais que o teto de 1800 s da chamada HTTP do Workflows.
    assert 'timeout = "21600s"' in job


def _segundos(texto: str) -> int:
    return int(texto.strip().removesuffix("s"))


def test_conector_de_cada_passo_espera_mais_que_o_timeout_do_job() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()
    texto = _texto()
    passos = {
        "valida": ("validacao", "- valida:", "- le_o_job:"),
        "transcreve": ("transcricao", "- transcreve:", "- le_a_tela:"),
        "le_a_tela": ("ocr", "- le_a_tela:", "- analisa:"),
        "analisa": ("analise", "- analisa:", "- fim:"),
    }
    for nome, (job, de, ate) in passos.items():
        recurso = main[main.index(f'resource "google_cloud_run_v2_job" "{job}"') :]
        recurso = recurso[: recurso.index("\n}\n")]
        job_s = _segundos(re.search(r'timeout\s*=\s*"(\d+s)"', recurso).group(1))  # type: ignore[union-attr]
        passo = texto[texto.index(de) : texto.index(ate)]
        conector = re.search(r"connector_params:\s+timeout: (\d+)", passo)
        assert conector is not None, nome
        assert int(conector.group(1)) > job_s, nome


def test_nenhum_comentario_da_infra_fala_em_ate_10_min() -> None:
    infra = Path(__file__).parents[2] / "infra"
    for arquivo in (infra / "main.tf", DEFINICAO):
        assert "até 10 min" not in arquivo.read_text()
