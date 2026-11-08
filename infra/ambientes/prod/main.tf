# Prod: o ar de verdade. Tamanhos e limites do dev até o piloto medir outros.
# Nada é criado por aqui (#293): sem CD e sem apply. O CI só roda `validate`. O que falta
# antes de aplicar e o que muda entre os ambientes está em infra/README.md.

terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
  # O bucket do estado vem por -backend-config (um por projeto); o prefixo é só deste ambiente.
  backend "gcs" {
    prefix = "prod"
  }
}

provider "google" {
  project        = var.projeto
  region         = var.regiao
  default_labels = { app = "mam", ambiente = "prod" }
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

variable "janelas_em_paralelo" {
  description = "Quantas janelas de análise o Job de análise decupa ao mesmo tempo"
  type        = number
  default     = 4
}

variable "vagas_de_gpu" {
  description = "Vagas da fila da GPU, uma por GPU, limitadas à cota disponível"
  type        = number
  default     = 3
  validation {
    condition     = floor(var.vagas_de_gpu) == var.vagas_de_gpu && var.vagas_de_gpu >= 1
    error_message = "vagas_de_gpu é um inteiro a partir de 1."
  }
}

variable "espera_gpu_minutos" {
  description = "Proteção contra falta de GPU ou cota fora da fila, em minutos, antes de falhar a etapa"
  type        = number
  default     = 27
}

variable "limite_de_falhas_por_etapa" {
  description = "Falhas por etapa, somando as origens (Jobs e Workflows), na janela dos alertas antes de alertar"
  type        = number
  default     = 3
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

variable "builds_de_imagem_guardados" {
  description = "Quantos builds de cada imagem o Artifact Registry guarda; os mais antigos são apagados"
  type        = number
  default     = 2
}

variable "dominio" {
  description = "Domínio do MAM. Vazio: sem balanceador e o endereço é o run.app; preenchido: nasce o balanceador HTTPS (#294)"
  type        = string
  default     = ""
}

module "mam" {
  source = "../../modulos/mam"

  projeto                      = var.projeto
  regiao                       = var.regiao
  admins_emergencia            = var.admins_emergencia
  imagem                       = var.imagem
  imagem_validacao             = var.imagem_validacao
  imagem_transcricao_gpu       = var.imagem_transcricao_gpu
  imagem_ocr_gpu               = var.imagem_ocr_gpu
  imagem_objetos               = var.imagem_objetos
  florence_modelo              = var.florence_modelo
  florence_feixes              = var.florence_feixes
  florence_lote                = var.florence_lote
  florence_legendas            = var.florence_legendas
  dominio                      = var.dominio
  waf_ativo                    = var.waf_ativo
  limite_de_requisicoes_por_ip = var.limite_de_requisicoes_por_ip
  ips_da_redetv                = var.ips_da_redetv
  vagas_de_gpu                 = var.vagas_de_gpu
  janelas_em_paralelo          = var.janelas_em_paralelo
  espera_gpu_minutos           = var.espera_gpu_minutos
  limite_de_falhas_por_etapa   = var.limite_de_falhas_por_etapa
  builds_de_imagem_guardados   = var.builds_de_imagem_guardados
}

output "identity_api_key" {
  value     = module.mam.identity_api_key
  sensitive = true
}

output "ip_do_balanceador" {
  value = module.mam.ip_do_balanceador
}

output "url" {
  value = module.mam.url
}

output "chave_mac_kms" {
  value = module.mam.chave_mac_kms
}

output "pubsub_topico_eventos" {
  value = module.mam.pubsub_topico_eventos
}

output "pubsub_topico_uso" {
  value = module.mam.pubsub_topico_uso
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

output "busca_indices_ligados" {
  value = module.mam.busca_indices_ligados
}

output "busca_dimensao" {
  value = module.mam.busca_dimensao
}

output "busca_cota_de_escrita" {
  value = module.mam.busca_cota_de_escrita
}

output "busca_distancia_maxima" {
  value = module.mam.busca_distancia_maxima
}

output "busca_palavras_minimas" {
  value = module.mam.busca_palavras_minimas
}

output "banco_de_seguranca" {
  value = module.mam.banco_de_seguranca
}

output "bucket_aceitos" {
  value = module.mam.bucket_aceitos
}

output "bucket_decupagens" {
  value = module.mam.bucket_decupagens
}

output "bucket_referencias" {
  value = module.mam.bucket_referencias
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
