"""O Job da avaliação diária e o agendamento no Terraform (#255), sem nuvem."""

import re
from pathlib import Path

TF = (Path(__file__).parents[2] / "infra" / "modulos" / "mam" / "main.tf").read_text()


def _bloco(cabecalho: str) -> str:
    inicio = TF.index(cabecalho)
    return TF[inicio : TF.index("\n}\n", inicio)]


def test_job_roda_o_modulo_da_avaliacao_com_a_conta_propria() -> None:
    job = _bloco('resource "google_cloud_run_v2_job" "avaliacao"')
    assert '"api.avaliacao_job"' in job
    assert 'google_service_account.mam["avaliacao"]' in job
    for nome in (
        "GCP_PROJECT_ID",
        "REGIAO_DA_AVALIACAO",
        "MODELO_DO_JUIZ",
        "BUCKET_ACEITOS",
        "BUCKET_DECUPAGENS",
        "FUSO_DA_AVALIACAO",
    ):
        assert f'"{nome}"' in job


def test_agendamento_dispara_o_job_com_a_conta_do_agendador() -> None:
    agenda = _bloco('resource "google_cloud_scheduler_job" "avaliacao"')
    assert "google_cloud_run_v2_job.avaliacao.name}:run" in agenda
    assert 'google_service_account.mam["agendador"]' in agenda
    assert re.search(r"cloudscheduler\.googleapis\.com", TF)


def test_agendador_so_roda_o_job_da_avaliacao() -> None:
    papel = _bloco(
        'resource "google_cloud_run_v2_job_iam_member" "agendador_roda_avaliacao"'
    )
    assert '"roles/run.invoker"' in papel
    assert re.search(r"agendador\s*=\s*\[\]", TF)


def test_job_e_agenda_usam_o_mesmo_fuso() -> None:
    job = _bloco('resource "google_cloud_run_v2_job" "avaliacao"')
    agenda = _bloco('resource "google_cloud_scheduler_job" "avaliacao"')
    assert "var.fuso_da_agenda" in job and "var.fuso_da_agenda" in agenda
