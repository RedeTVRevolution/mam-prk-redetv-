# Papéis sob medida da Vertex (#302, ADR 0002): no lugar do roles/aiplatform.user (mais de
# 400 permissões), só o que as chamadas usam. A predição cobre o generateContent do Gemini
# e o embedContent do Gemini Embedding. A Ranking API é do Discovery Engine
# (discoveryengine.viewer, na conta web), não da Vertex.
resource "google_project_iam_custom_role" "vertex_predicao" {
  project     = var.projeto
  role_id     = local.id_do_papel_vertex_predicao
  title       = "MAM: predição da Vertex"
  description = "Chamar modelos da Vertex (generateContent, embedContent); nada de gerir recursos."
  permissions = ["aiplatform.endpoints.predict"]
  depends_on  = [google_project_service.apis]
}

# O aceite dos esquemas no deploy (#617, api/aceite_dos_esquemas.py) chama o Gemini como a
# mam-terraform. Ela nasce no wizard, fora do Terraform; aqui só ganha a predição.
resource "google_project_iam_member" "terraform_predicao_vertex" {
  project = var.projeto
  role    = google_project_iam_custom_role.vertex_predicao.id
  member  = "serviceAccount:mam-terraform@${var.projeto}.iam.gserviceaccount.com"
}
