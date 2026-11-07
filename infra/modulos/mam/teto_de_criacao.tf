# Índice da contagem de Jobs criados na última hora por quem criou (teto de criação, #371):
# `criado_por` (`sistema:<nome>` ou o uid da pessoa) e `criado_em`, em ordem crescente,
# a ordem implícita da desigualdade em `criado_em` sem `order_by`.
resource "google_firestore_index" "teto_de_criacao" {
  database   = google_firestore_database.mam.name
  collection = "jobs"

  fields {
    field_path = "criado_por"
    order      = "ASCENDING"
  }
  fields {
    field_path = "criado_em"
    order      = "ASCENDING"
  }
}
