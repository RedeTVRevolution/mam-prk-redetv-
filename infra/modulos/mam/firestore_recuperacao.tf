# Backups do Firestore (#355): o Firestore guarda tudo o que não é arquivo, e o PITR
# (7 dias, ligado em `google_firestore_database.mam`) cobre o erro recente. As duas agendas
# são o máximo que o Firestore aceita por banco: uma diária, que guarda 7 dias, e uma
# semanal, que guarda 14 semanas (o teto da documentação). O backup volta sempre para um
# banco novo (infra/README.md).
resource "google_firestore_backup_schedule" "diaria" {
  database  = google_firestore_database.mam.name
  retention = "604800s" # 7 dias

  daily_recurrence {}
}

resource "google_firestore_backup_schedule" "semanal" {
  database  = google_firestore_database.mam.name
  retention = "8467200s" # 14 semanas

  weekly_recurrence {
    day = "SUNDAY"
  }
}
