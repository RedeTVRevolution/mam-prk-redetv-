# Job do aviso do fim (#379): o Workflows grava `falhou` direto no Firestore, sem passar pelo
# repositório da API, e chama este Job logo depois para publicar o evento de fim de Job
# (webhook) e o evento de uso. A mesma imagem do web, com outro comando; a falha já marcada
# só é avisada uma vez (`api.fim_do_job`).
resource "google_cloud_run_v2_job" "fim" {
  name                = "mam-fim"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["fim"].email
      max_retries     = 1
      timeout         = "300s"
      containers {
        image   = var.imagem
        command = ["python"]
        args    = ["-m", "api.fim_do_job"]
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
        env {
          name  = "PUBSUB_TOPICO_EVENTOS"
          value = google_pubsub_topic.eventos_do_job.id
        }
        env {
          name  = "PUBSUB_TOPICO_USO"
          value = google_pubsub_topic.eventos_de_uso.id
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
      }
    }
  }
  depends_on = [google_project_service.apis]
}

# A orquestração roda o Job do aviso, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_fim" {
  name     = google_cloud_run_v2_job.fim.name
  location = google_cloud_run_v2_job.fim.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}
