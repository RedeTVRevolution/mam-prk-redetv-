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
# Custo: cada rodada lê a tabela de eventos inteira, duas colunas (`job_id` e
# `duracao_do_video_ms`) da tabela de momentos inteira e as tabelas da própria rodada (o
# mínimo é 10 MB por tabela lida). No começo são uns 70 MB por rodada; a cada 10 minutos
# são ~4.300 rodadas por mês, uns 300 GB contra 1 TiB de consulta grátis por mês. Mas a
# conta cresce com o acervo: a leitura dos momentos custa ~45 bytes por momento, e com
# ~5 milhões de momentos copiados cada rodada já lê ~225 MB, ~1 TB por mês. Antes disso é
# preciso levar a duração no evento de fim de processamento ou guardar uma tabela pequena
# de duração por Job, e não ler os momentos. Estimado, não medido: conferir na fatura
# (`faturamento.tf`). O armazenamento fica nos 10 GB grátis.
locals {
  resumos_de_uso = ["uso_por_dia_e_usuario", "uso_por_dia", "uso_por_usuario", "uso_por_dia_e_programa"]
  # As que a web lê (PAINEL_TABELA_*): a API do painel não conhece o nome de nenhuma.
  tabelas_do_painel_na_web = {
    por_dia_e_usuario  = "uso_por_dia_e_usuario"
    por_dia_e_programa = "uso_por_dia_e_programa"
  }
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
      prefixo            = "${var.projeto}.${google_bigquery_dataset.decupagens.dataset_id}."
      tabela_de_eventos  = "${var.projeto}.${google_bigquery_dataset.decupagens.dataset_id}.${google_bigquery_table.eventos_de_uso.table_id}"
      tabela_de_momentos = "${var.projeto}.${google_bigquery_dataset.decupagens.dataset_id}.${google_bigquery_table.momentos.table_id}"
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
