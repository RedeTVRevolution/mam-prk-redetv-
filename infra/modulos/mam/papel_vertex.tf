# Papéis sob medida da Vertex (#302, ADR 0002): no lugar do roles/aiplatform.user (mais de
# 400 permissões), só o que as chamadas usam. A predição cobre o generateContent do Gemini
# e o embedContent do Gemini Embedding; a avaliação por rubrica (`evaluateInstances`) pede
# também aiplatform.locations.evaluateInstances. A Ranking API é do Discovery Engine
# (discoveryengine.viewer, na conta web), não da Vertex.
resource "google_project_iam_custom_role" "vertex_predicao" {
  project     = var.projeto
  role_id     = "mamVertexPredicao"
  title       = "MAM: predição da Vertex"
  description = "Chamar modelos da Vertex (generateContent, embedContent); nada de gerir recursos."
  permissions = ["aiplatform.endpoints.predict"]
  depends_on  = [google_project_service.apis]
}

resource "google_project_iam_custom_role" "vertex_avaliacao" {
  project     = var.projeto
  role_id     = "mamVertexAvaliacao"
  title       = "MAM: predição e avaliação da Vertex"
  description = "A predição mais o serviço de avaliação (evaluateInstances) da avaliação por rubrica."
  permissions = ["aiplatform.endpoints.predict", "aiplatform.locations.evaluateInstances"]
  depends_on  = [google_project_service.apis]
}
