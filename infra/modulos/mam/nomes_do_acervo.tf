# Os nomes próprios do acervo (#734): a busca lê esta tabela inteira (uma vez por hora por
# instância) e trata como o mesmo nome as grafias que só mudam na escrita ("Lordelo" e
# "Lordello", api/variantes.py). Refeita uma vez por dia pela consulta agendada, que lê só as
# colunas `tipo` e `texto` dos momentos; mesma conta dos resumos de uso (resumos_de_uso.tf).
resource "google_bigquery_table" "nomes_do_acervo" {
  dataset_id          = google_bigquery_dataset.decupagens.dataset_id
  table_id            = local.tabela_de_nomes_do_acervo
  deletion_protection = false # refeita por inteiro a cada dia
  schema = jsonencode([
    { name = "palavra", type = "STRING", mode = "NULLABLE", description = "Nome próprio sem acento e em minúsculas" },
    { name = "ocorrencias", type = "INTEGER", mode = "NULLABLE", description = "Vezes no acervo (fala, GC, plano e pauta)" },
  ])
}

resource "google_bigquery_data_transfer_config" "nomes_do_acervo" {
  display_name           = "mam-nomes-do-acervo"
  location               = var.regiao
  data_source_id         = "scheduled_query"
  schedule               = "every day 06:00"
  service_account_name   = google_service_account.resumos_de_uso.email
  destination_dataset_id = google_bigquery_dataset.decupagens.dataset_id
  params = {
    destination_table_name_template = google_bigquery_table.nomes_do_acervo.table_id
    write_disposition               = "WRITE_TRUNCATE"
    query = templatefile("${path.module}/nomes_do_acervo.sql", {
      tabela_de_momentos = "${var.projeto}.${google_bigquery_dataset.decupagens.dataset_id}.${google_bigquery_table.momentos_por_ano.table_id}"
    })
  }
  depends_on = [
    google_project_service.apis,
    google_project_iam_member.resumos_de_uso_roda_consulta,
    google_bigquery_dataset_iam_member.resumos_de_uso_grava,
  ]
}
