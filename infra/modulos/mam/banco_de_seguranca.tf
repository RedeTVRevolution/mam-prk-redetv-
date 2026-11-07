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

# Os mesmos índices no banco de segurança. Os do `(default)` (main.tf) ficam até a migração da
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

# As mesmas agendas de backup do `(default)` (firestore_recuperacao.tf): o limite de duas é
# por banco, e a auditoria e os papéis precisam voltar tanto quanto o resto.
resource "google_firestore_backup_schedule" "diaria_na_seguranca" {
  database  = google_firestore_database.seguranca.name
  retention = "604800s" # 7 dias

  daily_recurrence {}
}

resource "google_firestore_backup_schedule" "semanal_na_seguranca" {
  database  = google_firestore_database.seguranca.name
  retention = "8467200s" # 14 semanas

  weekly_recurrence {
    day = "SUNDAY"
  }
}
