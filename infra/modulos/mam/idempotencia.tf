# Chaves de idempotência do `POST /v1/jobs` (#274, E7): o Firestore apaga a reserva 48 h
# depois de criada (`expira_em`, `api/idempotencia.py`). A coleção `chaves_de_idempotencia`
# não precisa de índice: só se lê pelo id do documento.
resource "google_firestore_field" "idempotencia_expira_em" {
  database   = google_firestore_database.mam.name
  collection = "chaves_de_idempotencia"
  field      = "expira_em"

  ttl_config {}

  # Sem índice próprio: o TTL varre o campo sem ele, e cada índice a mais custa escrita.
  index_config {}
}
