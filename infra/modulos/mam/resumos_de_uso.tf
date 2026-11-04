# Tabelas resumidas do painel da diretoria (#280, E9). Uma consulta agendada do BigQuery
# (`resumos_de_uso.sql`) refaz `uso_por_dia_e_usuario`, `uso_por_dia`, `uso_por_usuario` e
# `uso_por_dia_e_programa` a partir de `eventos_de_uso` (#279) e as telas do painel (#282 a
# #285) leem só elas.
#
# Por que consulta agendada e não visão materializada: a visão materializada não aceita
# COUNT(DISTINCT) exato (usuários ativos, dias ativos), função de janela (descartar o evento
# repetido pelo `id`) nem a junção com os momentos (horas de vídeo). Refazer as tabelas de
# uma vez também dispensa saber o que mudou.
#
# Custo: o volume é pequeno. Cada rodada lê a tabela de eventos, duas colunas dos momentos e
# as tabelas temporárias, no máximo uns 60 MB cobrados (o mínimo é 10 MB por tabela lida);
# a cada 10 minutos são ~4.300 rodadas por mês, uns 260 GB contra 1 TiB de consulta grátis
# por mês. O armazenamento fica nos 10 GB grátis. Conferir na fatura (`faturamento.tf`) depois
# de alguns dias; se a tabela de eventos crescer, trocar por `every 30 minutes`.
locals {
  resumos_de_uso = ["uso_por_dia_e_usuario", "uso_por_dia", "uso_por_usuario", "uso_por_dia_e_programa"]
}

# A conta que roda a consulta: lê os eventos e os momentos e cria as tabelas no dataset.
resource "google_service_account" "resumos_de_uso" {
  account_id   = "mam-resumos-de-uso"
  display_name = "MAM resumos de uso"
}

resource "google_project_iam_member" "resumos_de_uso_roda_consulta" {
  project = var.projeto
  role    = "roles/bigquery.jobUser"
  member  = google_service_account.resumos_de_uso.member
}

resource "google_bigquery_dataset_iam_member" "resumos_de_uso_grava" {
  dataset_id = google_bigquery_dataset.decupagens.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.resumos_de_uso.member
}

resource "google_bigquery_data_transfer_config" "resumos_de_uso" {
  display_name         = "mam-resumos-de-uso"
  location             = var.regiao_do_bigquery
  data_source_id       = "scheduled_query"
  schedule             = "every 10 minutes"
  service_account_name = google_service_account.resumos_de_uso.email
  params = {
    query = templatefile("${path.module}/resumos_de_uso.sql", {
      p = "${var.projeto}.${google_bigquery_dataset.decupagens.dataset_id}."
    })
  }
  depends_on = [
    google_project_service.apis,
    google_project_iam_member.resumos_de_uso_roda_consulta,
    google_bigquery_dataset_iam_member.resumos_de_uso_grava,
    google_bigquery_table.eventos_de_uso,
    google_bigquery_table.momentos,
  ]
}

output "bigquery_tabelas_do_painel" {
  description = "Tabelas resumidas do painel da diretoria, no dataset das decupagens"
  value       = local.resumos_de_uso
}
