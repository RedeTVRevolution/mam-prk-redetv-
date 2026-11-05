# `cortes_ms` do Job (#361) é uma lista sem teto, de 3.500 a 7.000 números num vídeo de 3–4 h, e o
# Firestore indexaria cada elemento. Só se lê com o Job, nunca se filtra por ele: sem índice.
resource "google_firestore_field" "jobs_cortes_ms" {
  database   = google_firestore_database.mam.name
  collection = "jobs"
  field      = "cortes_ms"

  index_config {}
}
