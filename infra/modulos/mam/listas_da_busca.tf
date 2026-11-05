# Listas da busca paginada (#426): a 1ª página grava o resultado inteiro, e as seguintes
# o leem pelo cursor. O Firestore apaga a lista depois do `expira_em` (15 min,
# `api/busca.py`). A coleção `listas_da_busca` não precisa de índice: só se lê pelo id do
# documento. A conta da API já tem `roles/datastore.user` (main.tf): nenhum papel novo.
resource "google_firestore_field" "listas_da_busca_expira_em" {
  database   = google_firestore_database.mam.name
  collection = "listas_da_busca"
  field      = "expira_em"

  ttl_config {}

  # Sem índice próprio: o TTL varre o campo sem ele, e cada índice a mais custa escrita.
  index_config {}
}
