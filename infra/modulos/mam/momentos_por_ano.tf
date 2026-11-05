# Momentos dividida por ano de exibição (#356). A `momentos` (por dia) chega ao teto de 10.000
# partições com 25 anos de acervo (~9.500 dias) e cada dia tem só ~6 MB; por ano são ~25
# partições de ~2 GB. Tabela nova porque a antiga tem `deletion_protection` e o
# `aplicar-sem-destruir.sh` recusa recriar. Mesmo esquema e clustering da antiga.
resource "google_bigquery_table" "momentos_por_ano" {
  dataset_id          = google_bigquery_dataset.decupagens.dataset_id
  table_id            = local.tabela_de_momentos
  deletion_protection = true
  time_partitioning {
    type  = "YEAR"
    field = "data_de_exibicao"
  }
  clustering = ["programa", "job_id"]
  schema     = local.esquema_dos_momentos
}
