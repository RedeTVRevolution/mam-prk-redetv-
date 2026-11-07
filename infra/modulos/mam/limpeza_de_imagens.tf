# O resultado da limpeza (o ensaio, e agora as versões apagadas de verdade, #456) só aparece no log
# Data Access (DATA_WRITE), que vem desligado. Ele também registra os envios de imagem do CD
# (estimativa: alguns MB por mês, longe dos 50 GiB grátis do Logging). Ele manda só no bloco de
# auditoria desse serviço (ADR 0002). Fica ligado depois de ligar a limpeza: é por ele que se vê o
# que saiu, e desligá-lo faria o plano mostrar um delete, que o #456 não quer. Para desligar mais
# tarde, tirar o recurso: o plano pede PERMITIR_DESTRUICAO=sim.
resource "google_project_iam_audit_config" "artifact_registry" {
  project = var.projeto
  service = "artifactregistry.googleapis.com"
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}
