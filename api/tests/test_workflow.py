"""Definição do Workflows da validação: o comportamento real é conferido no #14."""

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


def test_chama_a_analise_so_se_o_job_esta_em_analisando() -> None:
    texto = _texto()

    leitura = texto.index("documents.get")
    condicao = texto.index('estado.stringValue == "analisando"')
    chamada = texto.index("call: http.post")
    assert leitura < condicao < chamada
    assert "${url_da_analise}/analisar" in texto
    assert "type: OIDC" in texto
    assert "audience: ${url_da_analise}" in texto
    # Fora de `analisando` o fluxo pula a chamada.
    assert "next: fim" in texto
    # O teto da chamada HTTP do Workflows está registrado.
    assert "timeout: 1800" in texto and "ponytail:" in texto


def test_falha_da_chamada_de_analise_grava_analise_falhou() -> None:
    texto = _texto()

    depois_da_chamada = texto[texto.index("call: http.post") :]
    assert "except:" in depois_da_chamada and "as: e" in depois_da_chamada
    assert "stringValue: analise_falhou" in depois_da_chamada
    assert "stringValue: falhou" in depois_da_chamada
    assert "raise: $${e}" in depois_da_chamada


def test_falha_da_chamada_nao_sobrescreve_job_que_ja_saiu_de_analisando() -> None:
    texto = _texto()

    depois_da_chamada = texto[texto.index("call: http.post") :]
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
