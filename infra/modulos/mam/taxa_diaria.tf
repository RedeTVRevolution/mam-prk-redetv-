# A taxa de correção por dia (#455, parte 1 de 2). A aba Revisão calculava a taxa na hora: lia as
# correções e baixava a decupagem inteira (~0,5 MB) de cada vídeo revisado, um por vez (17 a 50 min
# para 10 mil vídeos, contra o timeout de 300 s). Agora um Job agendado (`api/taxa_diaria.py`)
# refaz os últimos dias nesta tabela, e a parte 2 (#468) faz o painel só somar dias.
#
# Gatilho: Cloud Scheduler a cada hora, refazendo hoje e ontem (dia de São Paulo, o do painel). Os dados da conta estão em
# três lugares (correções e revisão no Firestore, Job concluído, contagem no Storage) e são
# gravados por vários processos (a API, a web, os Jobs do Cloud Run e o Workflows); ligar cada
# um a uma atualização pediria um tópico novo e o código de publicar em todos. A hora de
# atraso é aceitável para um painel de qualidade. Um Job reprocessado muda dias antigos (a versão
# do JSON muda e as correções antigas saem): depois do `make reprocessar-versao`, rode
# `make preencher-taxa-diaria`, que refaz o último ano. Ver README.
#
# Particionada por dia: a parte 2 filtra por período. Sem cluster: a tabela tem poucas linhas
# (dia × Job × ~25 tipos).
resource "google_bigquery_table" "taxa_de_correcao_por_dia" {
  dataset_id          = google_bigquery_dataset.decupagens.dataset_id
  table_id            = local.tabela_da_taxa_de_correcao
  deletion_protection = true
  time_partitioning {
    type  = "DAY"
    field = "dia"
  }
  schema = jsonencode([
    { name = "dia", type = "DATE", mode = "REQUIRED", description = "Dia de São Paulo; partição da tabela" },
    { name = "programa", type = "STRING", mode = "NULLABLE" },
    { name = "versao_pipeline", type = "STRING", mode = "NULLABLE", description = "Nulo na decupagem anterior à versão" },
    { name = "tipo", type = "STRING", mode = "REQUIRED", description = "Tipo de correção (pessoa.renomear, pauta.titulo...)" },
    { name = "correcoes", type = "INTEGER", mode = "REQUIRED", description = "Correções em vigor que passaram a valer no dia" },
    { name = "itens", type = "INTEGER", mode = "REQUIRED", description = "Itens do tipo nas decupagens revisadas no dia" },
    { name = "job_id", type = "STRING", mode = "NULLABLE", description = "Job revisado; nulo apenas nas linhas anteriores à nova carga do histórico (#509)" },
  ])
}

output "bigquery_tabela_da_taxa" {
  description = "Tabela da taxa de correção por dia, no dataset das decupagens: BIGQUERY_TABELA_DA_TAXA"
  value       = local.tabela_da_taxa_de_correcao
}

variable "agenda_da_taxa_diaria" {
  description = "Cron (formato do Cloud Scheduler) que refaz hoje e ontem na tabela da taxa de correção por dia (#455); a cada hora"
  type        = string
  default     = "10 * * * *"
}

resource "google_cloud_run_v2_job" "taxa_diaria" {
  name                = "mam-taxa-diaria"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["taxa"].email
      max_retries     = 0
      # Quem falha é refeito na hora seguinte, junto com o resto.
      timeout = "900s"
      containers {
        image   = var.imagem
        command = ["python"]
        args    = ["-m", "api.taxa_diaria"]
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
          name  = "FIRESTORE_BANCO"
          value = var.banco_firestore
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
          name  = "BIGQUERY_DATASET"
          value = local.dataset_do_bigquery
        }
        env {
          name  = "BIGQUERY_TABELA_DA_TAXA"
          value = local.tabela_da_taxa_de_correcao
        }
        env {
          name  = "BIGQUERY_REGIAO"
          value = var.regiao_do_bigquery
        }
      }
    }
  }
  depends_on = [
    google_project_service.apis,
    google_storage_bucket_iam_member.mam,
    google_bigquery_table.taxa_de_correcao_por_dia,
  ]
}

resource "google_cloud_run_v2_job_iam_member" "agendador_roda_taxa_diaria" {
  name     = google_cloud_run_v2_job.taxa_diaria.name
  location = google_cloud_run_v2_job.taxa_diaria.location
  role     = "roles/run.invoker"
  member   = google_service_account.mam["agendador"].member
}

resource "google_cloud_scheduler_job" "taxa_diaria" {
  name      = "mam-taxa-diaria-horaria"
  region    = var.regiao
  schedule  = var.agenda_da_taxa_diaria
  time_zone = var.fuso_da_agenda
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.projeto}/locations/${google_cloud_run_v2_job.taxa_diaria.location}/jobs/${google_cloud_run_v2_job.taxa_diaria.name}:run"
    oauth_token {
      service_account_email = google_service_account.mam["agendador"].email
    }
  }
  depends_on = [google_project_service.apis, google_cloud_run_v2_job_iam_member.agendador_roda_taxa_diaria]
}
