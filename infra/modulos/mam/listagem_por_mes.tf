# Índices da lista por envio com período (#479): os filtros do `acervo` (main.tf) com
# `mes_exibicao` (`in`) e a ordem por envio, cada combinação, inclusive só o mês. Fora do
# main.tf porque nasceram no módulo, sem `moved`.
locals {
  indices_do_acervo_por_mes = {
    for n in range(0, 16) : tostring(n) => [
      for j, campo in local.campos_do_acervo : campo
      if floor(n / pow(2, j)) % 2 == 1
    ]
  }
}

resource "google_firestore_index" "acervo_por_mes" {
  for_each   = local.indices_do_acervo_por_mes
  database   = google_firestore_database.mam.name
  collection = "jobs"

  dynamic "fields" {
    for_each = each.value
    content {
      field_path   = fields.value
      order        = fields.value == "palavras" ? null : "ASCENDING"
      array_config = fields.value == "palavras" ? "CONTAINS" : null
    }
  }
  fields {
    field_path = "mes_exibicao"
    order      = "ASCENDING"
  }
  fields {
    field_path = "criado_em"
    order      = "DESCENDING"
  }
}
