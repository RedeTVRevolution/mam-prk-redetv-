# Eventos de uso (#279, E9): a API e os Jobs publicam no tópico (`api/eventos_de_uso.py`) e
# uma assinatura do BigQuery grava cada mensagem na tabela `eventos_de_uso`, no dataset das
# decupagens, para o painel da diretoria. A tabela tem as colunas do esquema do tópico.
locals {
  quem_publica_uso         = toset(["web", "validacao", "transcricao", "ocr", "analise"])
  tabela_de_eventos_de_uso = "eventos_de_uso"
}

resource "google_pubsub_schema" "evento_de_uso" {
  name       = "mam-evento-de-uso"
  type       = "PROTOCOL_BUFFER"
  definition = file("${path.module}/evento_de_uso.proto")
  depends_on = [google_project_service.apis]
}

resource "google_pubsub_topic" "eventos_de_uso" {
  name       = "mam-eventos-de-uso"
  depends_on = [google_pubsub_schema.evento_de_uso]
  schema_settings {
    schema   = google_pubsub_schema.evento_de_uso.id
    encoding = "JSON"
  }
}

resource "google_bigquery_table" "eventos_de_uso" {
  dataset_id          = google_bigquery_dataset.decupagens.dataset_id
  table_id            = local.tabela_de_eventos_de_uso
  deletion_protection = true
  time_partitioning {
    type  = "DAY"
    field = "quando"
  }
  clustering = ["tipo", "quem_id"]
  schema = jsonencode([
    { name = "id", type = "STRING", mode = "REQUIRED", description = "Id do evento; a mesma ação pode chegar duas vezes, descarte a repetida por ele" },
    { name = "tipo", type = "STRING", mode = "REQUIRED", description = "login, envio, fim_de_processamento, busca, correcao ou chamada_de_api" },
    { name = "quando", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "quem_tipo", type = "STRING", mode = "REQUIRED", description = "usuario ou sistema" },
    { name = "quem_id", type = "STRING", mode = "REQUIRED", description = "uid ou nome do sistema; nunca nome nem e-mail" },
    { name = "job_id", type = "STRING", mode = "NULLABLE" },
    { name = "programa", type = "STRING", mode = "NULLABLE" },
    { name = "tamanho_bytes", type = "INTEGER", mode = "NULLABLE", description = "Só no envio" },
    { name = "estado", type = "STRING", mode = "NULLABLE", description = "Só no fim de processamento: concluido ou falhou" },
    { name = "codigo_falha", type = "STRING", mode = "NULLABLE" },
    { name = "tamanho_da_consulta", type = "INTEGER", mode = "NULLABLE", description = "Só na busca; o texto nunca é gravado" },
    {
      name = "filtros", type = "RECORD", mode = "REPEATED", description = "Só na busca",
      fields = [
        { name = "nome", type = "STRING", mode = "REQUIRED" },
        { name = "valor", type = "STRING", mode = "REQUIRED" },
      ]
    },
    { name = "tipo_de_correcao", type = "STRING", mode = "NULLABLE" },
    { name = "metodo", type = "STRING", mode = "NULLABLE", description = "Só na chamada de API" },
    { name = "rota", type = "STRING", mode = "NULLABLE" },
    { name = "status", type = "INTEGER", mode = "NULLABLE" },
    { name = "segundos_de_processamento", type = "INTEGER", mode = "NULLABLE", description = "Só no fim de processamento: do registro do Job ao fim" },
    { name = "n_resultados", type = "INTEGER", mode = "NULLABLE", description = "Só na busca: quantos vídeos trouxe; 0 é busca sem resultado" },
  ])
}

# Publica só neste tópico, e não no projeto.
resource "google_pubsub_topic_iam_member" "publica_uso" {
  for_each = local.quem_publica_uso
  topic    = google_pubsub_topic.eventos_de_uso.name
  role     = "roles/pubsub.publisher"
  member   = google_service_account.mam[each.key].member
}

# O agente de serviço do Pub/Sub grava na tabela (só nela) e lê o esquema dela.
resource "google_bigquery_table_iam_member" "pubsub_grava_uso" {
  for_each   = toset(["roles/bigquery.dataEditor", "roles/bigquery.metadataViewer"])
  dataset_id = google_bigquery_table.eventos_de_uso.dataset_id
  table_id   = google_bigquery_table.eventos_de_uso.table_id
  role       = each.key
  member     = local.agente_do_pubsub
}

resource "google_pubsub_subscription" "uso_no_bigquery" {
  name  = "mam-eventos-de-uso-bigquery"
  topic = google_pubsub_topic.eventos_de_uso.id
  bigquery_config {
    table            = "${var.projeto}.${google_bigquery_table.eventos_de_uso.dataset_id}.${google_bigquery_table.eventos_de_uso.table_id}"
    use_topic_schema = true
  }
  expiration_policy {
    ttl = ""
  }
  depends_on = [google_bigquery_table_iam_member.pubsub_grava_uso]
}

output "pubsub_topico_uso" {
  description = "Tópico dos eventos de uso: PUBSUB_TOPICO_USO na web e nos Jobs que publicam"
  value       = google_pubsub_topic.eventos_de_uso.id
}
