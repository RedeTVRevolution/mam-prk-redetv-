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
    # Um objeto sem Job correspondente não cria documento.
    assert "exists: true" in texto
    assert "googleapis.firestore.v1.projects.databases.documents.patch" in texto
    assert "arquivo_corrompido" in texto
    assert "falhou" in texto
