# O resultado do ensaio da limpeza só aparece no log Data Access (DATA_WRITE), que vem desligado.
# Ele também registra os envios de imagem do CD (estimativa: alguns MB por mês, longe dos 50 GiB
# grátis do Logging). Ele manda só no bloco de auditoria desse serviço (ADR 0002). Para desligar
# depois do ensaio, tirar o recurso: o plano mostra um delete e pede PERMITIR_DESTRUICAO=sim.
resource "google_project_iam_audit_config" "artifact_registry" {
  project = var.projeto
  service = "artifactregistry.googleapis.com"
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}
