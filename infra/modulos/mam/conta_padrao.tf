data "google_project" "este" {}

# Tira o Editor da conta padrão do Compute (#301): nada do MAM roda com ela, todo recurso
# declara a sua conta. Remoção pontual, sem reescrever a política (exceção da ADR 0002).
resource "google_project_iam_member_remove" "editor_da_conta_padrao" {
  project = var.projeto
  role    = "roles/editor"
  member  = "serviceAccount:${data.google_project.este.number}-compute@developer.gserviceaccount.com"
}
