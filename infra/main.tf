# Dev: o módulo do MAM com o estado e as variáveis de sempre (#292). Aplicado por
# `make deploy-dev`, à mão ou no CD (#71), que impersona a conta mam-terraform.
# O que muda de endereço ao entrar no módulo está nos blocos `moved` abaixo: o
# Terraform renomeia no estado em vez de destruir e recriar.

terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
  # O bucket vem por -backend-config; o `make deploy-dev` cria esse bucket.
  backend "gcs" {
    prefix = "dev"
  }
}

provider "google" {
  project        = var.projeto
  region         = var.regiao
  default_labels = { app = "mam" }
}

variable "projeto" {
  type = string
}

variable "regiao" {
  type = string
}

variable "admins_emergencia" {
  description = "E-mails dos administradores de emergência, separados por vírgula"
  type        = string
}

variable "imagem" {
  description = "Imagem do serviço, de preferência pelo digest"
  type        = string
}

variable "imagem_validacao" {
  description = "Imagem do Job de validação (--target validacao), de preferência pelo digest"
  type        = string
}

variable "imagem_transcricao" {
  description = "Imagem do Job de transcrição (--target transcricao), de preferência pelo digest"
  type        = string
}

variable "imagem_ocr" {
  description = "Imagem do Job de OCR da tela (--target ocr), de preferência pelo digest"
  type        = string
}

variable "imagem_transcricao_gpu" {
  description = "Imagem do Job de transcrição com GPU (--target transcricao-gpu), de preferência pelo digest"
  type        = string
}

variable "imagem_ocr_gpu" {
  description = "Imagem do Job de OCR da tela com GPU (--target ocr-gpu), de preferência pelo digest"
  type        = string
}

variable "imagem_objetos" {
  description = "Imagem do Job de objetos com GPU, Florence-2 (--target objetos-gpu), de preferência pelo digest"
  type        = string
}

variable "waf_ativo" {
  description = "Falso: as regras WAF do Cloud Armor só registram no log (prévia); verdadeiro: bloqueiam (#295)"
  type        = bool
  default     = false
}

variable "limite_de_requisicoes_por_ip" {
  description = "Requisições por minuto por IP no Cloud Armor (#295)"
  type        = number
  default     = 600
}

variable "ips_da_redetv" {
  description = "IPs ou CIDRs da RedeTV no Cloud Armor, até 10. Vazio: sem restrição de IP (#295)"
  type        = list(string)
  default     = []
}

variable "dominio" {
  description = "Domínio do MAM. Vazio: sem balanceador e o endereço é o run.app; preenchido: nasce o balanceador HTTPS (#294)"
  type        = string
  default     = ""
}

module "mam" {
  source = "./modulos/mam"

  projeto                      = var.projeto
  regiao                       = var.regiao
  admins_emergencia            = var.admins_emergencia
  imagem                       = var.imagem
  imagem_validacao             = var.imagem_validacao
  imagem_transcricao           = var.imagem_transcricao
  imagem_ocr                   = var.imagem_ocr
  imagem_transcricao_gpu       = var.imagem_transcricao_gpu
  imagem_ocr_gpu               = var.imagem_ocr_gpu
  imagem_objetos               = var.imagem_objetos
  dominio                      = var.dominio
  waf_ativo                    = var.waf_ativo
  limite_de_requisicoes_por_ip = var.limite_de_requisicoes_por_ip
  ips_da_redetv                = var.ips_da_redetv
}

output "identity_api_key" {
  value     = module.mam.identity_api_key
  sensitive = true
}

output "certificado_do_balanceador" {
  value = module.mam.certificado_do_balanceador
}

output "ip_do_balanceador" {
  value = module.mam.ip_do_balanceador
}

output "url" {
  value = module.mam.url
}

output "pubsub_topico_eventos" {
  value = module.mam.pubsub_topico_eventos
}

output "pubsub_topico_uso" {
  value = module.mam.pubsub_topico_uso
}

output "chave_mac_kms" {
  value = module.mam.chave_mac_kms
}

output "repositorio" {
  value = module.mam.repositorio
}

output "repositorio_gpu" {
  value = module.mam.repositorio_gpu
}

output "regiao_gpu" {
  value = module.mam.regiao_gpu
}

output "job_de_transcricao_gpu" {
  value = module.mam.job_de_transcricao_gpu
}

output "job_de_ocr_gpu" {
  value = module.mam.job_de_ocr_gpu
}

output "job_de_objetos_gpu" {
  value = module.mam.job_de_objetos_gpu
}

output "job_de_inventario" {
  value = module.mam.job_de_inventario
}

output "gpu_espera_total_s" {
  value = module.mam.gpu_espera_total_s
}

output "gpu_espera_maxima_s" {
  value = module.mam.gpu_espera_maxima_s
}

output "gpu_espera_s" {
  value = module.mam.gpu_espera_s
}

output "gpu_fator_da_espera" {
  value = module.mam.gpu_fator_da_espera
}

output "bigquery_dataset" {
  value = module.mam.bigquery_dataset
}

output "bigquery_tabela" {
  value = module.mam.bigquery_tabela
}

output "bigquery_regiao" {
  value = module.mam.bigquery_regiao
}

output "busca_regiao" {
  value = module.mam.busca_regiao
}

output "busca_colecao" {
  value = module.mam.busca_colecao
}

output "busca_colecao_de_medida" {
  value = module.mam.busca_colecao_de_medida
}

output "busca_indice_descricao" {
  value = module.mam.busca_indice_descricao
}

output "busca_indice_quadro" {
  value = module.mam.busca_indice_quadro
}

output "busca_dimensao" {
  value = module.mam.busca_dimensao
}

output "busca_distancia_maxima" {
  value = module.mam.busca_distancia_maxima
}

output "busca_palavras_minimas" {
  value = module.mam.busca_palavras_minimas
}

output "bucket_aceitos" {
  value = module.mam.bucket_aceitos
}

output "bucket_decupagens" {
  value = module.mam.bucket_decupagens
}

output "workflow_regiao" {
  value = module.mam.workflow_regiao
}

output "workflow_validacao" {
  value = module.mam.workflow_validacao
}

output "bucket_clipes_ouro" {
  value = module.mam.bucket_clipes_ouro
}

output "conta_build" {
  value = module.mam.conta_build
}

output "bucket_fontes" {
  value = module.mam.bucket_fontes
}

output "provedor_github" {
  value = module.mam.provedor_github
}

# Cada recurso do módulo tinha, antes, o endereço sem o prefixo `module.mam.`.
moved {
  from = google_project_service.apis
  to   = module.mam.google_project_service.apis
}

moved {
  from = google_artifact_registry_repository.mam
  to   = module.mam.google_artifact_registry_repository.mam
}

moved {
  from = google_artifact_registry_repository.mam_gpu
  to   = module.mam.google_artifact_registry_repository.mam_gpu
}

moved {
  from = google_firestore_database.mam
  to   = module.mam.google_firestore_database.mam
}

moved {
  from = google_firestore_index.acervo
  to   = module.mam.google_firestore_index.acervo
}

moved {
  from = google_firestore_index.auditoria
  to   = module.mam.google_firestore_index.auditoria
}

moved {
  from = google_model_armor_template.consulta_da_busca
  to   = module.mam.google_model_armor_template.consulta_da_busca
}

moved {
  from = google_storage_bucket.mam
  to   = module.mam.google_storage_bucket.mam
}

moved {
  from = google_service_account.mam
  to   = module.mam.google_service_account.mam
}

moved {
  from = google_project_iam_member.mam
  to   = module.mam.google_project_iam_member.mam
}

moved {
  from = google_storage_bucket_iam_member.mam
  to   = module.mam.google_storage_bucket_iam_member.mam
}

moved {
  from = google_service_account_iam_member.web_assina
  to   = module.mam.google_service_account_iam_member.web_assina
}

moved {
  from = google_storage_bucket.fontes
  to   = module.mam.google_storage_bucket.fontes
}

moved {
  from = google_storage_bucket_iam_member.build_le_fontes
  to   = module.mam.google_storage_bucket_iam_member.build_le_fontes
}

moved {
  from = google_artifact_registry_repository_iam_member.build_envia
  to   = module.mam.google_artifact_registry_repository_iam_member.build_envia
}

moved {
  from = google_artifact_registry_repository_iam_member.build_envia_gpu
  to   = module.mam.google_artifact_registry_repository_iam_member.build_envia_gpu
}

moved {
  from = google_iam_workload_identity_pool.github
  to   = module.mam.google_iam_workload_identity_pool.github
}

moved {
  from = google_iam_workload_identity_pool_provider.github
  to   = module.mam.google_iam_workload_identity_pool_provider.github
}

moved {
  from = google_bigquery_dataset.decupagens
  to   = module.mam.google_bigquery_dataset.decupagens
}

moved {
  from = google_bigquery_table.momentos
  to   = module.mam.google_bigquery_table.momentos
}

moved {
  from = google_bigquery_dataset_iam_member.grava_momentos
  to   = module.mam.google_bigquery_dataset_iam_member.grava_momentos
}

moved {
  from = google_service_account_iam_member.github_impersona_terraform
  to   = module.mam.google_service_account_iam_member.github_impersona_terraform
}

moved {
  from = google_cloud_run_v2_service.web
  to   = module.mam.google_cloud_run_v2_service.web
}

moved {
  from = google_compute_network.validacao
  to   = module.mam.google_compute_network.validacao
}

moved {
  from = google_compute_subnetwork.validacao
  to   = module.mam.google_compute_subnetwork.validacao
}

moved {
  from = google_compute_subnetwork.validacao_gpu
  to   = module.mam.google_compute_subnetwork.validacao_gpu
}

moved {
  from = google_cloud_run_v2_job.validacao
  to   = module.mam.google_cloud_run_v2_job.validacao
}

moved {
  from = google_cloud_run_v2_job.transcricao
  to   = module.mam.google_cloud_run_v2_job.transcricao
}

moved {
  from = google_cloud_run_v2_job.ocr
  to   = module.mam.google_cloud_run_v2_job.ocr
}

moved {
  from = google_cloud_run_v2_job.transcricao_gpu
  to   = module.mam.google_cloud_run_v2_job.transcricao_gpu
}

moved {
  from = google_cloud_run_v2_job.ocr_gpu
  to   = module.mam.google_cloud_run_v2_job.ocr_gpu
}

moved {
  from = google_cloud_run_v2_job.objetos_gpu
  to   = module.mam.google_cloud_run_v2_job.objetos_gpu
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_transcricao
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_transcricao
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_ocr
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_ocr
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_transcricao_gpu
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_transcricao_gpu
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_ocr_gpu
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_ocr_gpu
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_objetos_gpu
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_objetos_gpu
}

moved {
  from = google_cloud_run_v2_job.inventario
  to   = module.mam.google_cloud_run_v2_job.inventario
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_inventario
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_inventario
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda
}

moved {
  from = google_cloud_run_v2_job.analise
  to   = module.mam.google_cloud_run_v2_job.analise
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_analise
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_analise
}

moved {
  from = google_cloud_run_v2_job.quadros
  to   = module.mam.google_cloud_run_v2_job.quadros
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_quadros
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_quadros
}

moved {
  from = google_cloud_run_v2_job.indexacao
  to   = module.mam.google_cloud_run_v2_job.indexacao
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_indexacao
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_indexacao
}

moved {
  from = google_secret_manager_secret.serpapi
  to   = module.mam.google_secret_manager_secret.serpapi
}

moved {
  from = google_secret_manager_secret_iam_member.referencias_le_serpapi
  to   = module.mam.google_secret_manager_secret_iam_member.referencias_le_serpapi
}

moved {
  from = google_cloud_run_v2_job.referencias
  to   = module.mam.google_cloud_run_v2_job.referencias
}

moved {
  from = google_cloud_run_v2_job.identificacao
  to   = module.mam.google_cloud_run_v2_job.identificacao
}

moved {
  from = google_cloud_run_v2_job.comparacao
  to   = module.mam.google_cloud_run_v2_job.comparacao
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_identificacao
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_identificacao
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_referencias
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_referencias
}

moved {
  from = google_cloud_run_v2_job_iam_member.orquestracao_roda_comparacao
  to   = module.mam.google_cloud_run_v2_job_iam_member.orquestracao_roda_comparacao
}

moved {
  from = google_cloud_run_v2_job.avaliacao
  to   = module.mam.google_cloud_run_v2_job.avaliacao
}

moved {
  from = google_cloud_run_v2_job_iam_member.agendador_roda_avaliacao
  to   = module.mam.google_cloud_run_v2_job_iam_member.agendador_roda_avaliacao
}

moved {
  from = google_cloud_scheduler_job.avaliacao
  to   = module.mam.google_cloud_scheduler_job.avaliacao
}

moved {
  from = google_cloud_run_v2_job.fila
  to   = module.mam.google_cloud_run_v2_job.fila
}

moved {
  from = google_cloud_run_v2_job_iam_member.agendador_roda_fila
  to   = module.mam.google_cloud_run_v2_job_iam_member.agendador_roda_fila
}

moved {
  from = google_cloud_scheduler_job.fila
  to   = module.mam.google_cloud_scheduler_job.fila
}

moved {
  from = google_workflows_workflow.validacao
  to   = module.mam.google_workflows_workflow.validacao
}

moved {
  from = google_project_iam_member.storage_publica_eventos
  to   = module.mam.google_project_iam_member.storage_publica_eventos
}

moved {
  from = google_eventarc_trigger.quarentena
  to   = module.mam.google_eventarc_trigger.quarentena
}

moved {
  from = google_cloud_run_v2_service_iam_member.publico
  to   = module.mam.google_cloud_run_v2_service_iam_member.publico
}

moved {
  from = google_identity_platform_config.mam
  to   = module.mam.google_identity_platform_config.mam
}

moved {
  from = terraform_data.politica_de_senha
  to   = module.mam.terraform_data.politica_de_senha
}

moved {
  from = google_monitoring_notification_channel.admin_emergencia
  to   = module.mam.google_monitoring_notification_channel.admin_emergencia
}

moved {
  from = google_monitoring_alert_policy.login_admin_emergencia
  to   = module.mam.google_monitoring_alert_policy.login_admin_emergencia
}

moved {
  from = google_logging_metric.sinal_percentual
  to   = module.mam.google_logging_metric.sinal_percentual
}

moved {
  from = google_logging_metric.respostas_fora_do_esquema
  to   = module.mam.google_logging_metric.respostas_fora_do_esquema
}

moved {
  from = google_logging_metric.falhas_por_etapa
  to   = module.mam.google_logging_metric.falhas_por_etapa
}

moved {
  from = google_logging_metric.queda_da_avaliacao
  to   = module.mam.google_logging_metric.queda_da_avaliacao
}

moved {
  from = google_logging_metric.desvio_de_programa
  to   = module.mam.google_logging_metric.desvio_de_programa
}

moved {
  from = google_monitoring_alert_policy.sinal_percentual
  to   = module.mam.google_monitoring_alert_policy.sinal_percentual
}

moved {
  from = google_monitoring_alert_policy.fora_do_esquema
  to   = module.mam.google_monitoring_alert_policy.fora_do_esquema
}

moved {
  from = google_monitoring_alert_policy.falhas_por_etapa
  to   = module.mam.google_monitoring_alert_policy.falhas_por_etapa
}

moved {
  from = google_monitoring_alert_policy.queda_da_avaliacao
  to   = module.mam.google_monitoring_alert_policy.queda_da_avaliacao
}

moved {
  from = google_monitoring_alert_policy.desvio_de_programa
  to   = module.mam.google_monitoring_alert_policy.desvio_de_programa
}

moved {
  from = google_logging_metric.duracao_da_etapa
  to   = module.mam.google_logging_metric.duracao_da_etapa
}

moved {
  from = google_logging_metric.tokens_do_modelo
  to   = module.mam.google_logging_metric.tokens_do_modelo
}

moved {
  from = google_logging_metric.fila
  to   = module.mam.google_logging_metric.fila
}

moved {
  from = google_logging_metric.falta_de_gpu
  to   = module.mam.google_logging_metric.falta_de_gpu
}

moved {
  from = google_logging_metric.requisicoes_da_api
  to   = module.mam.google_logging_metric.requisicoes_da_api
}

moved {
  from = google_monitoring_dashboard.painel
  to   = module.mam.google_monitoring_dashboard.painel
}
