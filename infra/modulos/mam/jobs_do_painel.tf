# Uma linha por Job para as abas Revisão e Custo do painel (#454, parte 1 de 3). A Revisão e o
# Custo liam a coleção `jobs` inteira do Firestore a cada clique (cerca de 14 KB por Job); agora
# leem desta tabela, que guarda só o que elas usam: programa, duração, dono, estado e datas.
#
# Por que consulta agendada sobre os eventos de uso, e não um evento novo por mudança de Job:
# o `envio` e o `fim_de_processamento` já existem, já têm o publicador e as permissões em
# todo serviço que mexe no Job e já trazem tudo isso. Um tópico novo exigiria publicar de cada
# processo que grava o Job (a API e todos os Jobs do Cloud Run) a cada etapa. A consulta
# (`jobs_do_painel.sql`) refaz só os Jobs com evento na janela, na mesma cadência e com a mesma
# conta dos resumos de uso (`resumos_de_uso.tf`). O que os eventos não trazem (Jobs anteriores a
# eles) entra uma vez por `make preencher-jobs-do-painel`.
#
# Particionada por dia de `criado_em`: o sistema tem poucos anos de dias, bem abaixo do teto de
# 10.000 partições (a `momentos` por dia o atingia por usar a data de exibição, #356).
# Agrupada por programa e id: o filtro mais usado é o programa, e o id serve à troca das linhas.
resource "google_bigquery_table" "jobs_do_painel" {
  dataset_id          = google_bigquery_dataset.decupagens.dataset_id
  table_id            = local.tabela_de_jobs_do_painel
  deletion_protection = true
  time_partitioning {
    type  = "DAY"
    field = "criado_em"
  }
  clustering = ["programa", "id"]
  schema = jsonencode([
    { name = "id", type = "STRING", mode = "REQUIRED", description = "Id do Job" },
    { name = "programa", type = "STRING", mode = "NULLABLE" },
    { name = "duracao_ms", type = "INTEGER", mode = "NULLABLE", description = "Duração do vídeo; vazia no Job que falhou antes de medi-la" },
    { name = "quem_tipo", type = "STRING", mode = "NULLABLE", description = "Dono do Job: usuario ou sistema" },
    { name = "quem_id", type = "STRING", mode = "NULLABLE", description = "uid ou nome do sistema; nunca nome nem e-mail" },
    { name = "estado", type = "STRING", mode = "REQUIRED", description = "em_andamento até o fim; depois concluido ou falhou (o preenchimento dos Jobs antigos traz também cancelado)" },
    { name = "criado_em", type = "TIMESTAMP", mode = "REQUIRED", description = "Do envio; partição da tabela" },
    { name = "concluido_em", type = "TIMESTAMP", mode = "NULLABLE", description = "Do último fim de processamento (um reprocessamento o troca)" },
    { name = "atualizado_em", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_data_transfer_config" "jobs_do_painel" {
  display_name         = "mam-jobs-do-painel"
  location             = var.regiao
  data_source_id       = "scheduled_query"
  schedule             = "every 10 minutes"
  service_account_name = google_service_account.resumos_de_uso.email
  params = {
    query = templatefile("${path.module}/jobs_do_painel.sql", {
      tabela            = "${var.projeto}.${google_bigquery_dataset.decupagens.dataset_id}.${google_bigquery_table.jobs_do_painel.table_id}"
      tabela_de_eventos = "${var.projeto}.${google_bigquery_dataset.decupagens.dataset_id}.${google_bigquery_table.eventos_de_uso.table_id}"
      inicio_da_janela  = "TIMESTAMP(DATE_SUB(CURRENT_DATE('America/Sao_Paulo'), INTERVAL ${local.janela_dos_resumos_em_dias - 1} DAY), 'America/Sao_Paulo')"
    })
  }
  depends_on = [
    google_project_service.apis,
    google_project_iam_member.resumos_de_uso_roda_consulta,
    google_bigquery_dataset_iam_member.resumos_de_uso_grava,
    google_bigquery_table.eventos_de_uso,
    google_bigquery_table.jobs_do_painel,
  ]
}

output "bigquery_tabela_de_jobs" {
  description = "Tabela dos Jobs do painel (Revisão e Custo), no dataset das decupagens: BIGQUERY_TABELA_DE_JOBS"
  value       = local.tabela_de_jobs_do_painel
}
