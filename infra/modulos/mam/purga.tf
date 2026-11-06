# Purga automática da lixeira (#145): uma vez por dia o Job apaga o que está na lixeira há 30
# dias ou mais (`api/purga.py`). Sem acesso público: só o agendador o dispara, pelo IAM.
resource "google_cloud_run_v2_job" "purga" {
  name                = "mam-purga"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["purga"].email
      max_retries     = 0
      # Quem falha fica na lixeira e o dia seguinte tenta de novo.
      timeout = "1800s"
      containers {
        image   = var.imagem
        command = ["python"]
        args    = ["-m", "api.purga"]
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        env {
          name  = "BUCKET_DECUPAGENS"
          value = local.buckets["decupagens"]
        }
        env {
          name  = "BUSCA_REGIAO"
          value = var.regiao_da_busca
        }
        env {
          name  = "BUSCA_COLECAO"
          value = local.colecao_da_busca
        }
        env {
          name  = "BUSCA_INDICE_DESCRICAO"
          value = local.indice_da_descricao
        }
        env {
          name  = "BUSCA_INDICE_QUADRO"
          value = local.indice_do_quadro_em_uso
        }
        env {
          name  = "BUSCA_INDICES_LIGADOS"
          value = tostring(var.indices_da_busca_ligados)
        }
        env {
          name  = "BUSCA_DIMENSAO"
          value = tostring(var.dimensao_dos_vetores)
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

resource "google_cloud_run_v2_job_iam_member" "agendador_roda_purga" {
  name     = google_cloud_run_v2_job.purga.name
  location = google_cloud_run_v2_job.purga.location
  role     = "roles/run.invoker"
  member   = google_service_account.mam["agendador"].member
}

resource "google_cloud_scheduler_job" "purga" {
  name      = "mam-purga-diaria"
  region    = var.regiao
  schedule  = var.agenda_da_purga
  time_zone = var.fuso_da_agenda
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.projeto}/locations/${google_cloud_run_v2_job.purga.location}/jobs/${google_cloud_run_v2_job.purga.name}:run"
    oauth_token {
      service_account_email = google_service_account.mam["agendador"].email
    }
  }
  depends_on = [google_project_service.apis, google_cloud_run_v2_job_iam_member.agendador_roda_purga]
}
