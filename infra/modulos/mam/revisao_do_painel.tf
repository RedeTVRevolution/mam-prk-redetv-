# Uma linha por pessoa e vídeo para a aba Revisão do painel (#467, parte 3 de 3 do #454). O tempo de
# revisão vive no Firestore (`tempo_de_revisao`, uma medida por pessoa e vídeo) e a aba lia todas
# as medidas e cruzava com os Jobs em Python; agora a web copia cada medida para esta tabela (a
# cada pulso) e a aba pede ao BigQuery o resultado já agrupado, junto com `jobs_do_painel`.
#
# Mesma tabela, e não uma diária: a medida guarda o acumulado da pessoa no vídeo, então a linha é
# trocada (MERGE) a cada pulso e não há linha por dia para somar. Particionada por dia do último
# pulso, que é o filtro do período da aba, e agrupada por pessoa e vídeo, a chave da troca e o
# filtro por pessoa. Quem já tinha medidas antes entra uma vez por `make preencher-revisao-do-painel`.
resource "google_bigquery_table" "revisao_do_painel" {
  dataset_id          = google_bigquery_dataset.decupagens.dataset_id
  table_id            = local.tabela_de_revisao_do_painel
  deletion_protection = true
  time_partitioning {
    type  = "DAY"
    field = "ultimo_pulso"
  }
  clustering = ["uid", "job_id"]
  schema = jsonencode([
    { name = "job_id", type = "STRING", mode = "REQUIRED", description = "Id do Job" },
    { name = "uid", type = "STRING", mode = "REQUIRED", description = "Quem revisou" },
    { name = "email", type = "STRING", mode = "NULLABLE" },
    { name = "ativo_s", type = "FLOAT", mode = "REQUIRED", description = "Tempo ativo acumulado da pessoa no vídeo" },
    { name = "duracao_s", type = "FLOAT", mode = "NULLABLE", description = "Duração que a tela informou; a do Job vale mais" },
    { name = "ultimo_pulso", type = "TIMESTAMP", mode = "REQUIRED", description = "Do último pulso; partição da tabela" },
  ])
}

output "bigquery_tabela_de_revisao" {
  description = "Tabela das medidas de revisão do painel, no dataset das decupagens: BIGQUERY_TABELA_DE_REVISAO"
  value       = local.tabela_de_revisao_do_painel
}
