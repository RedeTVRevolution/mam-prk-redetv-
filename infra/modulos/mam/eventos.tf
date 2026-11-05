# Eventos de fim de Job para os webhooks (#273, E7). Quem termina um Job publica no tópico
# (`api/eventos_do_job.py`); a assinatura push chama a API (`POST /interno/webhook`), que
# entrega o webhook. Erro do destino volta como 503: o Pub/Sub espera, tenta de novo e,
# passado o limite, manda a mensagem para a fila de mensagens mortas.
locals {
  # Quem termina um Job: validação e análise (e o `falhou` de transcrição e OCR) rodam em Jobs
  # com a própria conta; os de GPU usam a mesma conta dos de CPU.
  quem_publica_eventos = toset(["validacao", "transcricao", "ocr", "analise", "fim"])
  # Texto que o token da assinatura leva como audiência; a API confere o mesmo.
  push_audiencia = "mam-webhook-push"
}

resource "google_pubsub_topic" "eventos_do_job" {
  name       = "mam-eventos-do-job"
  depends_on = [google_project_service.apis]
}

resource "google_pubsub_topic" "eventos_mortos" {
  name       = "mam-eventos-do-job-mortos"
  depends_on = [google_project_service.apis]
}

# A conta que o Pub/Sub usa para assinar o token da chamada push.
resource "google_service_account" "webhook_push" {
  account_id   = "mam-webhook-push"
  display_name = "MAM entrega de webhook (push do Pub/Sub)"
}

# Publica só neste tópico, e não no projeto.
resource "google_pubsub_topic_iam_member" "publica_eventos" {
  for_each = local.quem_publica_eventos
  topic    = google_pubsub_topic.eventos_do_job.name
  role     = "roles/pubsub.publisher"
  member   = google_service_account.mam[each.key].member
}

locals {
  agente_do_pubsub = "serviceAccount:service-${data.google_project.este.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# O agente de serviço do Pub/Sub gera o token da assinatura push (só nesta conta) ...
resource "google_service_account_iam_member" "pubsub_gera_o_token" {
  service_account_id = google_service_account.webhook_push.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.agente_do_pubsub
}

# ... e leva a mensagem esgotada à fila de mortas (publica nela e lê da assinatura).
resource "google_pubsub_topic_iam_member" "pubsub_publica_nas_mortas" {
  topic  = google_pubsub_topic.eventos_mortos.name
  role   = "roles/pubsub.publisher"
  member = local.agente_do_pubsub
}

resource "google_pubsub_subscription_iam_member" "pubsub_confirma_a_esgotada" {
  subscription = google_pubsub_subscription.entrega_do_webhook.name
  role         = "roles/pubsub.subscriber"
  member       = local.agente_do_pubsub
}

resource "google_pubsub_subscription" "entrega_do_webhook" {
  name  = "mam-entrega-do-webhook"
  topic = google_pubsub_topic.eventos_do_job.id
  # Cabe a entrega de um POST (o http da API espera até 30 s).
  ack_deadline_seconds = 60
  # Sete dias para a API voltar antes de a mensagem se perder.
  message_retention_duration = "604800s"
  push_config {
    push_endpoint = "${google_cloud_run_v2_service.web.uri}/interno/webhook"
    oidc_token {
      service_account_email = google_service_account.webhook_push.email
      audience              = local.push_audiencia
    }
  }
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.eventos_mortos.id
    max_delivery_attempts = 10
  }
  # A assinatura não expira por falta de uso.
  expiration_policy {
    ttl = ""
  }
  depends_on = [google_pubsub_topic_iam_member.pubsub_publica_nas_mortas]
}

# Quem olha a fila de mortas lê esta assinatura; sem ela, a mensagem esgotada some em 7 dias
# sem ninguém ver.
resource "google_pubsub_subscription" "eventos_mortos" {
  name                       = "mam-eventos-do-job-mortos"
  topic                      = google_pubsub_topic.eventos_mortos.id
  message_retention_duration = "604800s"
  expiration_policy {
    ttl = ""
  }
}

output "pubsub_topico_eventos" {
  description = "Tópico do fim de Job: PUBSUB_TOPICO_EVENTOS nos Jobs que terminam um Job"
  value       = google_pubsub_topic.eventos_do_job.id
}
