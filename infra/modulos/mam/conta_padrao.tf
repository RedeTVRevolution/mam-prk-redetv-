data "google_project" "este" {
  project_id = var.projeto
}

# Tira o Editor da conta padrão do Compute (#301): nada do MAM roda com ela, todo recurso
# declara a sua conta. Remoção pontual, sem reescrever a política (exceção da ADR 0002).
# O Google cria a conta e dá o Editor quando a API do Compute é ligada, daí o depends_on.
# Destruir este recurso não devolve o papel.
resource "google_project_iam_member_remove" "editor_da_conta_padrao" {
  project = var.projeto
  role    = "roles/editor"
  member  = "serviceAccount:${data.google_project.este.number}-compute@developer.gserviceaccount.com"

  depends_on = [google_project_service.apis]
}
