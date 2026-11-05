# Tabelas resumidas do painel da diretoria (#280, E9). Uma consulta agendada do BigQuery
# (`resumos_de_uso.sql`) mantém `uso_por_dia_e_usuario`, `uso_por_dia`, `uso_por_usuario` e
# `uso_por_dia_e_programa`, `correcoes_por_dia` e `chamadas_de_api_por_dia` a partir de `eventos_de_uso` (#279) e as telas do painel (#282 a
# #285) leem só elas.
#
# Por que consulta agendada e não visão materializada: a visão materializada não aceita
# COUNT(DISTINCT) exato (usuários ativos, dias ativos) nem função de janela (descartar o
# evento repetido pelo `id`).
#
# Custo (#380): cada rodada lê só as partições de `eventos_de_uso` da janela (hoje o dia de
# ontem e o de hoje, em São Paulo), as quatro tabelas por dia que ela troca e a de fins já
# contados; não lê os momentos (a duração do vídeo vem no evento de fim). Por isso o custo
# não cresce com o acervo, só com o uso de cada dia. Cada rodada ainda lê o mínimo de 10 MB
# por tabela. Medir no primeiro `apply` com `bq query --dry_run` (bytes antes e depois).
# Backfill ou correção de dias antigos: aumente `janela_dos_resumos_em_dias` por uma
# rodada e volte ao valor normal.
locals {
  # Quantos dias para trás (contando o de hoje em São Paulo) cada rodada refaz. O evento chega
  # em minutos e cai no dia dele; a folga cobre uma rodada que falhou e a virada do dia.
  janela_dos_resumos_em_dias = 2
  resumos_de_uso = ["uso_por_dia_e_usuario", "uso_por_dia", "uso_por_usuario", "uso_por_dia_e_programa", "correcoes_por_dia", "chamadas_de_api_por_dia"]
  # As que a web lê (PAINEL_TABELA_*): a API do painel não conhece o nome de nenhuma.
  tabelas_do_painel_na_web = {
    por_dia_e_usuario  = "uso_por_dia_e_usuario"
    por_dia_e_programa = "uso_por_dia_e_programa"
    correcoes_por_dia  = "correcoes_por_dia"
    chamadas_por_dia   = "chamadas_de_api_por_dia"
  }
}

# A conta que roda a consulta: lê os eventos e cria as tabelas no dataset.
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
      inicio_da_janela   = "TIMESTAMP(DATE_SUB(CURRENT_DATE('America/Sao_Paulo'), INTERVAL ${local.janela_dos_resumos_em_dias - 1} DAY), 'America/Sao_Paulo')"
    })
  }
  depends_on = [
    google_project_service.apis,
    google_project_iam_member.resumos_de_uso_roda_consulta,
    google_bigquery_dataset_iam_member.resumos_de_uso_grava,
    google_bigquery_table.eventos_de_uso,
  ]
}

output "bigquery_tabelas_do_painel" {
  description = "Tabelas resumidas do painel da diretoria, no dataset das decupagens"
  value       = local.resumos_de_uso
}
