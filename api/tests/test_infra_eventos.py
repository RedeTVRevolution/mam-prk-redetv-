"""Pub/Sub dos eventos de fim de Job (#273): tópicos, push, fila de mortas e IAM."""

import re
from pathlib import Path

MODULO = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
EVENTOS = (MODULO / "eventos.tf").read_text()
MAIN = (MODULO / "main.tf").read_text()


def _bloco(texto: str, cabecalho: str) -> str:
    inicio = texto.index(cabecalho)
    return texto[inicio : texto.index("\n}\n", inicio)]


def test_a_assinatura_push_tem_token_espera_e_fila_de_mortas() -> None:
    bloco = _bloco(
        EVENTOS, 'resource "google_pubsub_subscription" "entrega_do_webhook"'
    )

    assert "/interno/webhook" in bloco
    assert (
        "oidc_token" in bloco and "google_service_account.webhook_push.email" in bloco
    )
    assert "retry_policy" in bloco
    assert "dead_letter_topic" in bloco and "max_delivery_attempts" in bloco


def test_o_agente_do_pubsub_gera_o_token_e_publica_so_na_fila_de_mortas() -> None:
    token = _bloco(
        EVENTOS, 'resource "google_service_account_iam_member" "pubsub_gera_o_token"'
    )
    mortas = _bloco(
        EVENTOS, 'resource "google_pubsub_topic_iam_member" "pubsub_publica_nas_mortas"'
    )

    assert "roles/iam.serviceAccountTokenCreator" in token
    assert "google_service_account.webhook_push.name" in token
    assert "roles/pubsub.publisher" in mortas
    assert "google_pubsub_topic.eventos_mortos.name" in mortas
    assert "google_project_iam_member" not in EVENTOS


def test_quem_publica_so_publica_no_topico() -> None:
    bloco = _bloco(
        EVENTOS, 'resource "google_pubsub_topic_iam_member" "publica_eventos"'
    )

    assert "roles/pubsub.publisher" in bloco
    assert "google_pubsub_topic.eventos_do_job.name" in bloco


def test_os_jobs_que_terminam_um_job_recebem_o_topico_por_variavel_de_ambiente() -> (
    None
):
    for job in [
        "validacao",
        "transcricao_gpu",
        "ocr_gpu",
        "analise",
    ]:
        bloco = _bloco(MAIN, f'resource "google_cloud_run_v2_job" "{job}"')
        assert re.search(
            r'name\s+= "PUBSUB_TOPICO_EVENTOS"\s+value\s+= google_pubsub_topic.eventos_do_job.id',
            bloco,
        ), job


def test_o_cofre_do_webhook_e_um_segredo_com_cmek_na_regiao() -> None:
    chave = _bloco(EVENTOS, 'resource "google_kms_crypto_key" "segredos_do_webhook"')
    segredo = _bloco(
        EVENTOS, 'resource "google_secret_manager_secret" "segredos_do_webhook"'
    )

    assert 'purpose  = "ENCRYPT_DECRYPT"' in chave
    assert "google_kms_key_ring.mam.id" in chave
    # A chave CMEK fica na mesma região da réplica (o key ring é regional).
    assert "user_managed" in segredo and "location = var.regiao" in segredo
    assert "kms_key_name = google_kms_crypto_key.segredos_do_webhook.id" in segredo
    assert "google_kms_crypto_key_iam_member.secret_manager_cifra" in segredo


def test_so_a_web_le_o_segredo_e_o_agente_do_secret_manager_cifra() -> None:
    leitura = _bloco(
        EVENTOS,
        'resource "google_secret_manager_secret_iam_member" "web_le_os_segredos"',
    )
    cifra = _bloco(
        EVENTOS, 'resource "google_kms_crypto_key_iam_member" "secret_manager_cifra"'
    )

    assert "roles/secretmanager.secretAccessor" in leitura
    assert 'google_service_account.mam["web"].member' in leitura
    assert "roles/cloudkms.cryptoKeyEncrypterDecrypter" in cifra
    assert "gcp-sa-secretmanager.iam.gserviceaccount.com" in cifra
    assert EVENTOS.count("google_secret_manager_secret_iam_member") == 1


def test_a_web_recebe_a_configuracao_do_push_e_do_cofre() -> None:
    web = _bloco(MAIN, 'resource "google_cloud_run_v2_service" "web"')
    for nome, valor in [
        ("PUSH_AUDIENCIA", "local.push_audiencia"),
        ("PUSH_CONTA", "google_service_account.webhook_push.email"),
        ("WEBHOOK_SEGREDOS", "google_secret_manager_secret.segredos_do_webhook.id"),
    ]:
        assert re.search(rf'name\s+= "{nome}"\s+value\s+= {re.escape(valor)}', web), (
            nome
        )
