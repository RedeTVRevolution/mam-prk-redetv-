# Banco só de segurança (#368/#464): papéis, chaves de API e auditoria. Os Jobs que abrem
# conteúdo hostil não têm acesso a ele (condição IAM por banco, mais abaixo). É o único
# lugar que monta o nome; o código o recebe por FIRESTORE_BANCO_DE_SEGURANCA (api/bancos.py).
locals {
  banco_de_seguranca = "mam-seguranca"
}

resource "google_firestore_database" "seguranca" {
  name                              = local.banco_de_seguranca
  location_id                       = var.regiao
  type                              = "FIRESTORE_NATIVE"
  delete_protection_state           = "DELETE_PROTECTION_ENABLED"
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  depends_on                        = [google_project_service.apis]
}

# Os mesmos índices no banco de segurança. Os do `(default)` (acima) ficam até a migração da
# auditoria (#368, parte 3): trocar o banco do recurso antigo o destruiria.
resource "google_firestore_index" "auditoria_na_seguranca" {
  for_each   = local.indices_da_auditoria
  database   = google_firestore_database.seguranca.name
  collection = "auditoria"

  dynamic "fields" {
    for_each = each.value
    content {
      field_path = fields.value
      order      = "ASCENDING"
    }
  }
  fields {
    field_path = "quando"
    order      = "DESCENDING"
  }
}
