# Destino da exportação do faturamento (#281), lida pelo painel de custo (#285), na região
# do `mam_decupagens` para as duas se cruzarem numa consulta. A exportação se liga uma vez no
# console da conta de faturamento: não há API nem Terraform para ela. Ao ligar, o console dá
# escrita no dataset a uma conta de serviço da Google; por isso o IAM deste dataset é só com
# `_iam_member`, que acrescenta. Um `_iam_policy`, um `_iam_binding` ou um bloco `access` aqui
# apagaria esse acesso no deploy seguinte, e a exportação pararia calada. Recurso novo, sem
# `moved`: nunca existiu fora do módulo.
locals {
  dataset_do_faturamento = "faturamento_${local.marca_da_regiao}"
}

resource "google_bigquery_dataset" "faturamento" {
  dataset_id                 = local.dataset_do_faturamento
  location                   = var.regiao
  delete_contents_on_destroy = false
  depends_on                 = [google_project_service.apis]
}

# A `mam-web` lê a exportação para a aba Custo do painel. Só `_iam_member`, pelo motivo acima.
resource "google_bigquery_dataset_iam_member" "faturamento_le" {
  dataset_id = google_bigquery_dataset.faturamento.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = google_service_account.mam["web"].member
}
