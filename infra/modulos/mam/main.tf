# Infraestrutura de um ambiente do MAM (E0, #8; módulo desde #292). O ambiente chama
# este módulo (infra/main.tf para o dev); o backend e o provider ficam lá. O dev é aplicado
# por `make deploy-dev`, à mão ou no CD (#71), que impersona a conta mam-terraform. No IAM do projeto, só
# google_project_iam_member, que é aditivo (ADR 0002).

terraform {
  required_version = ">= 1.9"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
  }
}

variable "projeto" {
  type = string
}

variable "regiao" {
  type = string
}

# O Agent Retrieval não existe em southamerica-east1: o índice da busca fica nos EUA (ADR 0006).
variable "regiao_da_busca" {
  type    = string
  default = "us-east4"
}

# O Model Armor existe em southamerica-east1 (lista de locais de 2/11/2026), então a
# consulta do editor não sai do Brasil para ser julgada; a Ranking API é global e fica
# fora do Brasil (ADR 0006).
variable "regiao_do_model_armor" {
  type    = string
  default = "southamerica-east1"
}

# A cópia das decupagens no BigQuery (#260) fica no Brasil: os dados não saem do país.
variable "regiao_do_bigquery" {
  type    = string
  default = "southamerica-east1"
}

# Os Jobs de transcrição e de OCR com GPU L4 rodam aqui (ADR 0007). Cloud Run não tem GPU
# em southamerica-east1. Só processamento de passagem: nenhum bucket nasce nesta região.
variable "regiao_gpu" {
  type    = string
  default = "us-east4"
}

# Falta de GPU ou de cota: a mesma espera vale para o Workflows (#239) e para o teste
# depois da publicação (scripts/testar-jobs-gpu.sh, que lê os outputs gpu_*). O Job com GPU
# tenta de novo, esperando `gpu_espera_s` antes da segunda tentativa e, a cada vez, a espera
# anterior vezes `gpu_fator_da_espera`, com teto em `gpu_espera_maxima_s`, até a soma das
# esperas passar de `espera_gpu_minutos`; o número de tentativas sai dessa conta. Com os
# padrões: 1, 2, 4, 4 e 4 minutos, seis tentativas em 15 minutos. Só depois disso o Workflows
# roda o Job em CPU.
variable "espera_gpu_minutos" {
  description = "Espera total por GPU ou cota, em minutos, antes do plano B em CPU"
  type        = number
  default     = 15
  validation {
    condition     = floor(var.espera_gpu_minutos) == var.espera_gpu_minutos && var.espera_gpu_minutos >= 0
    error_message = "espera_gpu_minutos é um inteiro a partir de 0 (com 0, a GPU é tentada uma vez só antes da CPU)."
  }
}

# Leitura da tela só quando a imagem muda (#233, api/mudanca_da_tela.py): diferença média
# (0 a 255) de um dos blocos (seis faixas horizontais de oito blocos) do quadro, contra o último quadro lido, acima
# da qual o OCR lê de novo. 0 lê todo quadro, como antes. O padrão é um palpite; a medição no
# ar (#240, `make comparar-leituras`) acerta o valor sem nova imagem.
variable "limiar_de_mudanca_do_ocr" {
  description = "Limiar de mudança da imagem para o OCR ler de novo (0 = lê todo quadro)"
  type        = number
  default     = 3
  validation {
    condition     = var.limiar_de_mudanca_do_ocr >= 0
    error_message = "limiar_de_mudanca_do_ocr é zero ou mais."
  }
}

variable "gpu_espera_s" {
  type    = number
  default = 60
  validation {
    condition     = floor(var.gpu_espera_s) == var.gpu_espera_s && var.gpu_espera_s >= 1
    error_message = "gpu_espera_s é um inteiro a partir de 1 (o script do teste faz a conta em bash)."
  }
}

variable "gpu_fator_da_espera" {
  type    = number
  default = 2
  validation {
    condition     = floor(var.gpu_fator_da_espera) == var.gpu_fator_da_espera && var.gpu_fator_da_espera >= 1
    error_message = "gpu_fator_da_espera é um inteiro a partir de 1 (o script do teste faz a conta em bash)."
  }
}

variable "gpu_espera_maxima_s" {
  type    = number
  default = 240
  validation {
    condition     = floor(var.gpu_espera_maxima_s) == var.gpu_espera_maxima_s && var.gpu_espera_maxima_s >= 1
    error_message = "gpu_espera_maxima_s é um inteiro a partir de 1 (o script do teste faz a conta em bash)."
  }
}

variable "dimensao_dos_vetores" {
  description = "Dimensão dos vetores da busca; fixa na criação da coleção"
  type        = number
  default     = 256
}

# O índice ANN do quadro-chave está ligado no dev desde o #268 (ADR 0006): cada índice
# cobra réplicas por hora, e com a variável em false o código não calcula o vetor do
# quadro. Ligar só cria o índice (make criar-colecao-da-busca, depois do apply).
variable "indice_do_quadro_ligado" {
  type    = bool
  default = true
}

# O corte do que a busca acha só pelo significado (vetor): a distância de cosseno máxima
# e o mínimo de palavras do registro. Calibrados em 3 vídeos do dev; mudar aqui e aplicar.
variable "busca_distancia_maxima" {
  type    = number
  default = 0.25
}

variable "busca_palavras_minimas" {
  type    = number
  default = 3
}

variable "admins_emergencia" {
  description = "E-mails dos administradores de emergência, separados por vírgula"
  type        = string
}

variable "dominio" {
  description = "Domínio do MAM (ex.: mam.exemplo.com.br). Vazio: sem balanceador, e o endereço é o run.app. Preenchido: nasce o balanceador HTTPS e o Cloud Run só aceita o tráfego dele (#294)"
  type        = string
  default     = ""
}

variable "waf_ativo" {
  description = "Falso: as regras WAF do Cloud Armor só registram no log o que bloqueariam (prévia). Verdadeiro: bloqueiam de verdade (403). Ligue depois de olhar os logs da prévia (#295)"
  type        = bool
  default     = false
}

variable "limite_de_requisicoes_por_ip" {
  description = "Requisições por minuto por IP no Cloud Armor; acima disso, 429 (#295)"
  type        = number
  default     = 600
}

variable "ips_da_redetv" {
  description = "IPs ou CIDRs da RedeTV no Cloud Armor, até 10 (limite do Google por regra). Vazio: sem restrição de IP. Preenchido: só eles passam, em todas as rotas, as /v1 dos sistemas inclusive (#295)"
  type        = list(string)
  default     = []

  validation {
    condition     = length(var.ips_da_redetv) <= 10
    error_message = "O Cloud Armor aceita até 10 IPs ou CIDRs por regra."
  }

  validation {
    condition     = alltrue([for ip in var.ips_da_redetv : can(cidrhost(strcontains(ip, "/") ? ip : "${ip}/32", 0))])
    error_message = "Cada item de ips_da_redetv precisa ser um IP ou CIDR (ex.: 200.1.2.0/24)."
  }
}

variable "imagem" {
  description = "Imagem do serviço, de preferência pelo digest"
  type        = string
}

variable "janelas_em_paralelo" {
  description = "Quantas janelas de análise o Job de análise decupa ao mesmo tempo"
  type        = number
  # ponytail: 4 é um chute; o valor sai do piloto e da cota do Gemini.
  default = 4
}

variable "tolerancia_da_fala_ms" {
  description = "Folga, em ms, entre o nome dito no Whisper e a pessoa na imagem para a fala provar o nome"
  type        = number
  default     = 2000
}

variable "validade_das_referencias_dias" {
  description = "Dias em que uma foto de referência da web vale, a contar de quando foi obtida; depois disso é buscada de novo"
  type        = number
  default     = 180
}

variable "prazo_dos_palpites_dias" {
  description = "Dias até apagar as fotos de um palpite fora do catálogo que não se confirmou (rosto é dado sensível); vale só para o prefixo palpites/ do bucket de referências"
  type        = number
  default     = 30
}

variable "limite_de_buscas_por_video" {
  description = "Quantas buscas no SerpAPI o Job de referências faz por vídeo; depois disso não busca mais"
  type        = number
  default     = 12
}

variable "referencias_do_acervo" {
  description = "\"ligado\" liga o uso das referências de rosto do acervo (caminho pronto, desligado por padrão)"
  type        = string
  default     = "desligado"
}

variable "limite_de_pessoas_do_modelo_forte" {
  description = "Quantas pessoas sem nome por vídeo o modelo forte olha (as de mais tempo na imagem primeiro)"
  type        = number
  default     = 8
}

variable "limiar_da_comparacao" {
  description = "Confiança mínima de cada uma das 3 fotos para a comparação confirmar um nome"
  type        = number
  default     = 0.8
}

variable "limite_de_comparacoes" {
  description = "Quantas pessoas por vídeo a comparação com as fotos de referência examina; as demais ficam como palpite não confirmado"
  type        = number
  default     = 8
}

variable "regiao_da_avaliacao" {
  description = "Região do serviço de avaliação da Vertex (evaluateInstances é regional, não global)"
  type        = string
  default     = "us-central1"
}

variable "modelo_do_juiz" {
  description = "Modelo juiz da avaliação por rubrica (#255); confira no console se a região o oferece"
  type        = string
  default     = "gemini-2.5-flash"
}

variable "fracao_da_avaliacao" {
  description = "Fração dos vídeos concluídos no dia que a avaliação por rubrica examina (no mínimo 1 por programa)"
  type        = number
  default     = 0.1
}

variable "limiar_da_avaliacao" {
  description = "Nota média (0 a 100) de um requisito abaixo da qual a avaliação grava o log de queda"
  type        = number
  default     = 60
}

variable "queda_maxima_da_avaliacao" {
  description = "Pontos que a média de um requisito pode cair da média dos dias anteriores antes do log de queda"
  type        = number
  default     = 10
}

variable "janela_da_avaliacao_dias" {
  description = "Quantos dias anteriores formam a média de comparação da queda"
  type        = number
  default     = 7
}

variable "preco_por_mil_caracteres_da_avaliacao" {
  description = "US$ por mil caracteres do serviço de avaliação, para o custo estimado no log; vazio: não estima (preço não confirmado, #255)"
  type        = string
  default     = ""
}

variable "agenda_da_avaliacao" {
  description = "Cron (formato do Cloud Scheduler) da avaliação diária; roda depois da meia-noite e avalia o dia anterior"
  type        = string
  default     = "30 0 * * *"
}

variable "fuso_da_agenda" {
  description = "Fuso da agenda da avaliação e do dia que ela avalia"
  type        = string
  default     = "America/Sao_Paulo"
}

variable "limiar_de_escalonadas_pct" {
  description = "Média, na janela do alerta, do percentual de janelas escalonadas para o 3.8 Flash por vídeo, acima da qual o alerta dispara. O plano espera 10 a 15% do tempo; 25% é o dobro do esperado, e a amostra de controle sozinha já é 10%"
  type        = number
  default     = 25
}

variable "limiar_de_nao_identificadas_pct" {
  description = "Média, na janela do alerta, do percentual de pessoas na imagem sem nome por vídeo (antes do modelo forte), acima da qual o alerta dispara. Sem medida do piloto ainda: 50% é um chute largo, a ajustar com os dados reais (#286)"
  type        = number
  default     = 50
}

variable "limiar_de_fora_do_esquema" {
  description = "Respostas do modelo recusadas pelo esquema (e refeitas) na janela do alerta, acima das quais o alerta dispara. Cada vídeo longo faz dezenas de chamadas: 10 por dia é raro o bastante para indicar mudança do modelo ou do prompt"
  type        = number
  default     = 10
}

variable "limite_de_falhas_por_etapa" {
  description = "Falhas de uma mesma etapa na janela do alerta acima das quais o alerta dispara; vale para cada etapa e para cada origem em separado (as falhas tratadas pelos Jobs e as execuções que caíram no Workflows não se somam)"
  type        = number
  default     = 3
}

variable "janela_dos_alertas_horas" {
  description = "Horas de log que cada alerta de sinal de qualidade soma ou calcula a média; o volume é de poucos vídeos por dia, então a janela é de um dia"
  type        = number
  default     = 24
  validation {
    # O período de alinhamento de um alerta vai até um dia.
    condition     = var.janela_dos_alertas_horas >= 1 && var.janela_dos_alertas_horas <= 24 && floor(var.janela_dos_alertas_horas) == var.janela_dos_alertas_horas
    error_message = "janela_dos_alertas_horas: horas inteiras de 1 a 24."
  }
}

variable "janela_dos_paineis_horas" {
  description = "Horas de log que cada gráfico dos painéis de observabilidade (#288) soma ou resume; o volume é de poucos vídeos por dia, então a janela é de um dia"
  type        = number
  default     = 24
  validation {
    condition     = var.janela_dos_paineis_horas >= 1 && floor(var.janela_dos_paineis_horas) == var.janela_dos_paineis_horas
    error_message = "janela_dos_paineis_horas: horas inteiras, no mínimo 1."
  }
}

variable "precos_por_milhao_de_tokens" {
  description = "US$ por milhão de tokens de cada modelo (chave: o ID do modelo, como ele sai no log), para o custo por etapa do painel (#288); vazio: o painel mostra só os tokens (preço não confirmado)"
  type = map(object({
    entrada = number
    saida   = number
  }))
  default = {}
}

variable "agenda_da_fila" {
  description = "Cron (formato do Cloud Scheduler) da amostra da fila de processamento (#288); de minuto em minuto, o Job só conta os Jobs em andamento e loga"
  type        = string
  default     = "* * * * *"
}

variable "agenda_da_purga" {
  description = "Cron (formato do Cloud Scheduler) da purga automática da lixeira (#145); uma vez por dia, de madrugada"
  type        = string
  default     = "0 3 * * *"
}

variable "minutos_do_login_recente" {
  description = "Há quantos minutos, no máximo, foi o login com MFA que a purga manual exige (#145)"
  type        = number
  default     = 5
}

variable "videos_do_sinal_por_programa" {
  description = "N do sinal por programa (#287): quantos vídeos anteriores do mesmo programa formam a média e o desvio, e o mínimo para alertar (programa com menos vídeos não alerta)"
  type        = number
  default     = 10
  validation {
    condition     = var.videos_do_sinal_por_programa >= 2 && floor(var.videos_do_sinal_por_programa) == var.videos_do_sinal_por_programa
    error_message = "videos_do_sinal_por_programa: inteiro a partir de 2 (o desvio pede dois vídeos)."
  }
}

variable "desvios_do_sinal_por_programa" {
  description = "K do sinal por programa (#287): quantos desvios-padrão de distância da média do programa, em eventos por hora de vídeo, viram alerta. 3 é o convencional; sem dados do piloto, ajuste depois"
  type        = number
  default     = 3
  validation {
    condition     = var.desvios_do_sinal_por_programa > 0
    error_message = "desvios_do_sinal_por_programa: maior que zero."
  }
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

# Qual motor faz o inventário de objetos dos quadros (#243): o Florence-2, num Job com GPU,
# ou o Gemini, na análise. O Workflows lê o valor; o YAML ainda não o usa.
variable "motor_objetos" {
  description = "Motor do inventário de objetos: florence ou gemini"
  type        = string
  default     = "florence"
  validation {
    condition     = contains(["florence", "gemini"], var.motor_objetos)
    error_message = "motor_objetos vale florence ou gemini."
  }
}

# O modelo do Gemini do inventário de objetos (#244): converte o texto do Florence-2 para o
# português (motor florence) ou olha os quadros-chave (motor gemini). O mesmo Flash-Lite do
# restante (`api/gemini.py`, ADR 0004).
variable "modelo_objetos" {
  description = "Modelo do Gemini do inventário de objetos"
  type        = string
  default     = "gemini-3.5-flash-lite"
}

resource "google_project_service" "apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",             # cópia das decupagens para relatórios (#260)
    "bigquerydatatransfer.googleapis.com", # consulta agendada dos resumos de uso (#280)
    "cloudbuild.googleapis.com",
    "cloudkms.googleapis.com", # chave MAC do hash das chaves de API (#272)
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "eventarc.googleapis.com",
    "discoveryengine.googleapis.com", # Ranking API da busca (#232)
    "firestore.googleapis.com",
    "identitytoolkit.googleapis.com",
    "modelarmor.googleapis.com", # filtro de injeção da consulta da busca (#232)
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "sts.googleapis.com",
    "vectorsearch.googleapis.com",
    "workflows.googleapis.com",
    # Ligadas antes pelo wizard; aqui para que o Terraform as declare.
    "aiplatform.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "cloudscheduler.googleapis.com", # agendamento diário da avaliação por rubrica (#255)
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "mam" {
  repository_id = "mam"
  location      = var.regiao
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# As imagens com GPU (e o cache das camadas delas) ficam na região da GPU: o Cloud Run baixa
# a imagem de uma instância que sobe em us-east4, e o BuildKit, ao enviar a imagem, não
# reenvia as camadas que o cache já pôs no mesmo repositório.
resource "google_artifact_registry_repository" "mam_gpu" {
  repository_id = "mam-gpu"
  location      = var.regiao_gpu
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

resource "google_firestore_database" "mam" {
  name                    = "(default)"
  location_id             = var.regiao
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"
  depends_on              = [google_project_service.apis]
}

# Índices compostos da lista de Jobs (GET /v1/jobs, #141): cada combinação não vazia de
# programa, sistema, estado (`in`) e uma palavra do nome (`array-contains`), com a ordem
# por envio (criado_em) ou por exibição (data_exibicao). O intervalo de datas só vai ao
# Firestore na ordem por exibicao (ele fica no campo da ordem); na ordem por envio a
# API o confere depois da leitura.
locals {
  campos_do_acervo = ["programa", "sistema", "estado", "palavras"]
  indices_do_acervo = {
    for par in setproduct(range(1, 16), ["criado_em", "data_exibicao"]) :
    "${par[1]}-${par[0]}" => {
      ordem = par[1]
      campos = [
        for j, campo in local.campos_do_acervo : campo
        if floor(par[0] / pow(2, j)) % 2 == 1
      ]
    }
  }
}

resource "google_firestore_index" "acervo" {
  for_each   = local.indices_do_acervo
  database   = google_firestore_database.mam.name
  collection = "jobs"

  dynamic "fields" {
    for_each = each.value.campos
    content {
      field_path   = fields.value
      order        = fields.value == "palavras" ? null : "ASCENDING"
      array_config = fields.value == "palavras" ? "CONTAINS" : null
    }
  }
  fields {
    field_path = each.value.ordem
    order      = "DESCENDING"
  }
}

# Índices compostos da auditoria (GET /v1/admin/auditoria, #140): cada combinação não
# vazia de pessoa (`uid` ou `email`), alvo e ação, com o período e a ordem em `quando`.
# A coleção só recebe acréscimos.
locals {
  campos_da_auditoria = ["uid", "email", "alvo_id", "acao"]
  indices_da_auditoria = {
    for n in range(1, 16) : tostring(n) => [
      for j, campo in local.campos_da_auditoria : campo
      if floor(n / pow(2, j)) % 2 == 1
    ]
    # `pessoa` é uid ou e-mail, nunca os dois na mesma consulta.
    if !(floor(n / 1) % 2 == 1 && floor(n / 2) % 2 == 1)
  }
}

resource "google_firestore_index" "auditoria" {
  for_each   = local.indices_da_auditoria
  database   = google_firestore_database.mam.name
  collection = "auditoria"

  dynamic "fields" {
    for_each = each.value
    content {
      field_path = fields.value
      order      = "ASCENDING"
    }
  }
  fields {
    field_path = "quando"
    order      = "DESCENDING"
  }
}

# O único lugar que monta os nomes dos buckets. O código os recebe por variável
# de ambiente (BUCKET_*), e o `make verificar` recusa sufixo escrito em api/ ou
# web/src/ (scripts/checar-nomes-da-nuvem.sh lê a lista desta linha).
locals {
  sufixos_dos_buckets = ["quarentena", "aceitos", "decupagens", "clipes-ouro", "referencias"]
  buckets             = { for s in local.sufixos_dos_buckets : s => "${var.projeto}-${s}" }
}

# A coleção de momentos da busca (#117) e os índices ANN dela (um por campo de vetor)
# nascem no `make criar-colecao-da-busca` (idempotente), porque o provedor do Terraform
# ainda não tem o recurso. Este é o único lugar que monta os nomes; o código os recebe
# por BUSCA_*. A coleção de medida é a temporária do `make medir-busca`.
locals {
  colecao_da_busca           = "momentos"
  colecao_de_medida_da_busca = "momentos-medida"
  indice_da_descricao        = "momentos-descricao-ann"
  indice_do_quadro           = "momentos-quadro-ann"
  # Vazio desliga o índice do quadro-chave no código (BUSCA_INDICE_QUADRO).
  indice_do_quadro_em_uso = var.indice_do_quadro_ligado ? local.indice_do_quadro : ""
  # O modelo do Model Armor e a configuração da Ranking API (a padrão, que já existe no
  # projeto) chegam ao serviço por MODEL_ARMOR_* e RANKING_CONFIG (#232).
  modelo_do_model_armor = "consulta-da-busca"
  config_da_ranking     = "default_ranking_config"
}

# O modelo (template) do Model Armor que julga a consulta antes de o Gemini vê-la: só o
# filtro de injeção de prompt e jailbreak, no nível que o `sanitizeUserPrompt` acusa
# com confiança média ou maior. Sem o filtro de conteúdo nocivo: a consulta é só uma frase
# de busca, e o Gemini já recusa o que é nocivo.
resource "google_model_armor_template" "consulta_da_busca" {
  location    = var.regiao_do_model_armor
  template_id = local.modelo_do_model_armor
  filter_config {
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "MEDIUM_AND_ABOVE"
    }
  }
  depends_on = [google_project_service.apis]
}

# clipes-ouro (#3): os 5 clipes do teste de contrato com o Gemini, nunca no git,
# e o clipe sintético do cassete (cassetes/).
# Sem papel de conta de serviço: por ora só o Owner e a mam-terraform os alcançam.
resource "google_storage_bucket" "mam" {
  for_each                    = local.buckets
  name                        = each.value
  location                    = var.regiao
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  # As fotos de um palpite fora do catálogo (#222) são apagadas sozinhas depois do prazo;
  # as ligadas a uma pessoa do catálogo ficam fora do prefixo e não são apagadas.
  dynamic "lifecycle_rule" {
    for_each = each.key == "referencias" ? [1] : []
    content {
      condition {
        age            = var.prazo_dos_palpites_dias
        matches_prefix = ["palpites/"]
      }
      action {
        type = "Delete"
      }
    }
  }
  # Só a quarentena recebe upload do navegador (retomável, direto no Storage),
  # e só das URLs da aplicação.
  dynamic "cors" {
    for_each = each.key == "quarentena" ? [1] : []
    content {
      origin          = local.origens_da_aplicacao
      method          = ["POST", "PUT"]
      response_header = ["Content-Type", "Content-Range", "x-goog-resumable", "x-upload-content-length", "Location", "Range"]
      max_age_seconds = 3600
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_service_account" "mam" {
  for_each     = toset(["web", "validacao", "transcricao", "ocr", "analise", "quadros", "indexacao", "referencias", "identificacao", "comparacao", "orquestracao", "objetos", "avaliacao", "fila", "purga", "agendador", "build"])
  account_id   = "mam-${each.key}"
  display_name = "MAM ${each.key}"
}

# Papéis de cada componente. A orquestração grava a falha da validação no
# Firestore, recebe o evento do Eventarc e invoca o Workflows (o provider não tem
# papel no próprio Workflows); o papel de rodar cada Job, inclusive o de análise, fica
# mais abaixo, no próprio Job (ADR 0002). Quem lê o
# proxy por gs:// na Vertex é a conta que chama (mam-analise, com acesso a
# aceitos), segundo a doc do generateContent; o agente de serviço da Vertex não
# precisa de papel no bucket. O run.viewer da orquestração fica no projeto porque o
# conector do Workflows acompanha a execução do Job pela operação, que é do projeto e
# não do Job; sem ele, o passo `valida` falharia depois de o Job rodar e marcaria um
# vídeo bom como arquivo_corrompido.
# A mam-referencias grava as referências no catálogo e chama o Gemini para conferir as fotos.
locals {
  # Os IDs dos papéis sob medida (papel_vertex.tf). As concessões são escritas pelo
  # ID, e não pelo atributo do recurso: o for_each do iam_member tira as chaves daqui,
  # e elas têm de ser conhecidas no plan (o depends_on do iam_member garante que o
  # papel existe antes da concessão).
  id_do_papel_vertex_predicao  = "mamVertexPredicao"
  id_do_papel_vertex_avaliacao = "mamVertexAvaliacao"
  papel_vertex_predicao        = "projects/${var.projeto}/roles/${local.id_do_papel_vertex_predicao}"
  papel_vertex_avaliacao       = "projects/${var.projeto}/roles/${local.id_do_papel_vertex_avaliacao}"

  papeis_no_projeto = {
    # `workflows.invoker` é só iniciar execuções (o reprocessar do #147), e o projeto tem
    # um único workflow.
    # `modelarmor.user` só saneia prompts (sanitizeUserPrompt); `discoveryengine.viewer` é o
    # menor papel com a permissão `discoveryengine.rankingConfigs.rank`, da Ranking API (#232).
    # `bigquery.jobUser` (web e indexacao): rodar o script que troca as linhas do Job na
    # cópia do BigQuery (#260); o acesso aos dados é só no dataset, mais abaixo.
    # `firebaseauth.admin` (web): criar, bloquear e listar as contas do Identity Platform
    # pelas rotas de usuários (#142).
    web         = ["roles/datastore.user", "roles/vectorsearch.dataObjectWriter", local.papel_vertex_predicao, "roles/workflows.invoker", "roles/modelarmor.user", "roles/discoveryengine.viewer", "roles/bigquery.jobUser", "roles/firebaseauth.admin"]
    validacao   = ["roles/datastore.user"]
    transcricao = ["roles/datastore.user"]
    ocr         = ["roles/datastore.user"]
    analise     = ["roles/datastore.user", local.papel_vertex_predicao]
    quadros     = ["roles/datastore.user"]
    # Grava o estado da indexação no Job e escreve na coleção da busca (gravar, apagar,
    # consultar e buscar; conferido no #122). A conta `web` tem o mesmo papel, porque
    # reindexa a cada Correção e busca. Nenhuma das duas cria ou apaga coleção. O
    # embedding automático da coleção roda com a credencial de quem grava ou busca, e não
    # com a do Agent Retrieval: as duas precisam chamar a Vertex (papel sob medida, só a predição).
    indexacao   = ["roles/datastore.user", "roles/vectorsearch.dataObjectWriter", local.papel_vertex_predicao, "roles/bigquery.jobUser"]
    referencias = ["roles/datastore.user", local.papel_vertex_predicao]
    # Leem o Job, o catálogo e a Decupagem no Firestore e chamam o Gemini; a comparação
    # também grava as sugestões de perfil.
    identificacao = ["roles/datastore.user", local.papel_vertex_predicao]
    comparacao    = ["roles/datastore.user", local.papel_vertex_predicao]
    # O Job do inventário chama o Gemini (texto, ou os quadros); não toca o Firestore.
    objetos = [local.papel_vertex_predicao]
    # A avaliação (#255) lê os Jobs, grava as notas no Firestore e chama o serviço de
    # avaliação da Vertex (`evaluateInstances`): papel sob medida com a predição e a
    # permissão do próprio `evaluateInstances` (#302).
    avaliacao = ["roles/datastore.user", local.papel_vertex_avaliacao]
    # A amostra da fila (#288) só lê os Jobs do Firestore e escreve no log.
    fila = ["roles/datastore.user"]
    # A purga automática (#145) apaga o Job e as correções no Firestore e os momentos do índice
    # (como a `web`, quando ela purga à mão).
    purga = ["roles/datastore.user", "roles/vectorsearch.dataObjectWriter"]
    # O agendador só dispara os Jobs da avaliação, da fila e da purga (papel em cada Job, mais abaixo).
    agendador = []
    # O logWriter é do `sys.log` do Workflows (falhas, duração da etapa): sem ele o passo cai com 403.
    orquestracao = ["roles/datastore.user", "roles/eventarc.eventReceiver", "roles/workflows.invoker", "roles/run.viewer", "roles/logging.logWriter"]
    # O Cloud Build com conta própria só grava log no Cloud Logging.
    build = ["roles/logging.logWriter"]
  }
  papeis_nos_buckets = {
    # A API assina as URLs de envio para a quarentena, apaga dela o upload cancelado e lê o proxy de reprodução e a decupagem.
    # Em aceitos também apaga o progresso das janelas, quando o Curador reprocessa a partir da análise (objectUser).
    # As referências: o link assinado das fotos do nome e, quando uma pessoa do catálogo vai
    # para a lixeira (#151), apagar as fotos de rosto dela (objectUser).
    # A purga manual (#145) apaga também a decupagem e os quadros: objectUser em decupagens.
    web = { quarentena = "roles/storage.objectUser", aceitos = "roles/storage.objectUser", decupagens = "roles/storage.objectUser", referencias = "roles/storage.objectUser" }
    # Lê e apaga o original da quarentena; grava a cópia limpa e o proxy de reprodução.
    validacao = { quarentena = "roles/storage.objectUser", aceitos = "roles/storage.objectCreator" }
    # Lê o áudio que a validação separou e grava a transcrição ao lado do proxy.
    transcricao = { aceitos = "roles/storage.objectUser" }
    # Lê o proxy e grava a leitura da tela ao lado dele.
    ocr = { aceitos = "roles/storage.objectUser" }
    # O Gemini lê o proxy de reprodução; o progresso das janelas é regravado ao lado dele
    # (objectUser, porque cada janela sobrescreve o próprio objeto); a decupagem vai para o
    # bucket dela (objectUser, porque o reprocessamento escolhido a sobrescreve).
    analise = { aceitos = "roles/storage.objectUser", decupagens = "roles/storage.objectUser" }
    # Lê a cópia limpa; grava os JPEGs e regrava a decupagem (objectUser, porque a sobrescreve).
    quadros = { aceitos = "roles/storage.objectViewer", decupagens = "roles/storage.objectUser" }
    # Lê a Decupagem entregue, com os quadros-chave.
    indexacao = { decupagens = "roles/storage.objectViewer" }
    # Grava as fotos de referência e lê a lista de nomes que a identificação deixou na decupagem.
    referencias = { referencias = "roles/storage.objectUser", decupagens = "roles/storage.objectViewer" }
    # Lê a cópia limpa e regrava a Decupagem (objectUser, porque a sobrescreve).
    identificacao = { aceitos = "roles/storage.objectViewer", decupagens = "roles/storage.objectUser" }
    # Como a identificação, mais as fotos de referência (lê, e passa as fotos do palpite
    # confirmado para o lugar das do catálogo, apagando as de antes: objectUser); grava
    # `<job>.comparacao.json`.
    comparacao = { aceitos = "roles/storage.objectViewer", decupagens = "roles/storage.objectUser", referencias = "roles/storage.objectUser" }
    # Lê a Decupagem e os quadros e grava o resultado do Florence-2 ao lado deles
    # (`<job>/objetos/florence.json`; objectUser, porque o reprocessamento o sobrescreve).
    # Só este bucket: o Job não lê o proxy nem toca o Firestore.
    # O Job em CPU do inventário (#244) usa a mesma conta: lê o resultado e os quadros e
    # regrava a Decupagem com o inventário no mesmo bucket.
    objetos = { decupagens = "roles/storage.objectUser" }
    # Só lê a Decupagem.
    avaliacao = { decupagens = "roles/storage.objectViewer" }
    # Apaga os arquivos do vídeo purgado: cópia limpa, proxy, janelas, decupagem e quadros.
    purga = { aceitos = "roles/storage.objectUser", decupagens = "roles/storage.objectUser" }
  }
}

resource "google_project_iam_member" "mam" {
  for_each = { for p in flatten([
    for sa, papeis in local.papeis_no_projeto : [for papel in papeis : { sa = sa, papel = papel }]
  ]) : "${p.sa}:${p.papel}" => p }
  project = var.projeto
  role    = each.value.papel
  member  = google_service_account.mam[each.value.sa].member
  depends_on = [
    google_project_iam_custom_role.vertex_predicao,
    google_project_iam_custom_role.vertex_avaliacao,
  ]
}

resource "google_storage_bucket_iam_member" "mam" {
  for_each = { for p in flatten([
    for sa, buckets in local.papeis_nos_buckets : [for bucket, papel in buckets : { sa = sa, bucket = bucket, papel = papel }]
  ]) : "${p.sa}:${p.bucket}" => p }
  bucket = google_storage_bucket.mam[each.value.bucket].name
  role   = each.value.papel
  member = google_service_account.mam[each.value.sa].member
}

# Assinar URLs sem chave em arquivo: a API pede a assinatura ao IAM como ela mesma.
resource "google_service_account_iam_member" "web_assina" {
  service_account_id = google_service_account.mam["web"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = google_service_account.mam["web"].member
}

# Build das imagens (#71): o `make deploy-dev`, à mão ou no CD, sobe o código para
# o bucket de fontes e o Cloud Build constrói como mam-build, que só lê as fontes e
# envia ao repositório. Bucket fora do mapa acima porque aquele depende do serviço,
# e o build vem antes dele. O scripts/checar-nomes-da-nuvem.sh conhece o sufixo.
resource "google_storage_bucket" "fontes" {
  name                        = "${var.projeto}-fontes"
  location                    = var.regiao
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  depends_on                  = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "build_le_fontes" {
  bucket = google_storage_bucket.fontes.name
  role   = "roles/storage.objectViewer"
  member = google_service_account.mam["build"].member
}

resource "google_artifact_registry_repository_iam_member" "build_envia" {
  repository = google_artifact_registry_repository.mam.name
  location   = google_artifact_registry_repository.mam.location
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.mam["build"].member
}

resource "google_artifact_registry_repository_iam_member" "build_envia_gpu" {
  repository = google_artifact_registry_repository.mam_gpu.name
  location   = google_artifact_registry_repository.mam_gpu.location
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.mam["build"].member
}

# CD (#71): o GitHub Actions entra sem chave, por federação (ADR 0002), e só a
# main deste repositório impersona a mam-terraform. Pelo id do repositório, e não
# pelo nome, para que outro repositório criado com o mesmo nome não herde a confiança.
locals {
  repositorio_github_id = "1436546057" # RedeTVRevolution/mam-prk-redetv-
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "mam-github"
  display_name              = "MAM GitHub"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository_id" = "assertion.repository_id"
  }
  attribute_condition = "assertion.repository_id == '${local.repositorio_github_id}' && assertion.ref == 'refs/heads/main'"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Cópia das decupagens no BigQuery (#260): uma linha por momento, para os relatórios de
# aparições e menções por pessoa, marca e programa. Este é o único lugar que monta os
# nomes; o código os recebe por BIGQUERY_*. Quem grava (indexação, no fim da análise e
# no `make copiar-para-bigquery`, e a web, a cada Correção) é dataEditor só no dataset.
locals {
  dataset_do_bigquery = "mam_decupagens"
  tabela_de_momentos  = "momentos"
}

resource "google_bigquery_dataset" "decupagens" {
  dataset_id                 = local.dataset_do_bigquery
  location                   = var.regiao_do_bigquery
  delete_contents_on_destroy = false
  depends_on                 = [google_project_service.apis]
}

resource "google_bigquery_table" "momentos" {
  dataset_id          = google_bigquery_dataset.decupagens.dataset_id
  table_id            = local.tabela_de_momentos
  deletion_protection = true
  time_partitioning {
    type  = "DAY"
    field = "data_de_exibicao"
  }
  clustering = ["programa", "job_id"]
  schema = jsonencode([
    { name = "job_id", type = "STRING", mode = "REQUIRED" },
    { name = "programa", type = "STRING", mode = "NULLABLE" },
    { name = "data_de_exibicao", type = "DATE", mode = "NULLABLE" },
    { name = "tipo", type = "STRING", mode = "REQUIRED", description = "plano, fala, texto_na_tela, objeto, comercial, pauta, aparicao, mencao_na_fala ou mencao_no_texto" },
    { name = "inicio_ms", type = "INTEGER", mode = "REQUIRED" },
    { name = "fim_ms", type = "INTEGER", mode = "REQUIRED" },
    {
      name = "pessoas", type = "RECORD", mode = "REPEATED", description = "Quem aparece no momento; no objeto, o dono",
      fields = [
        { name = "id", type = "STRING", mode = "NULLABLE" },
        { name = "nome", type = "STRING", mode = "NULLABLE" },
      ]
    },
    { name = "marca", type = "STRING", mode = "NULLABLE" },
    { name = "tipo_de_insercao", type = "STRING", mode = "NULLABLE", description = "Só no comercial" },
    { name = "texto", type = "STRING", mode = "NULLABLE" },
    { name = "versao_pipeline", type = "STRING", mode = "NULLABLE" },
    { name = "gravado_em", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "duracao_do_video_ms", type = "INTEGER", mode = "NULLABLE", description = "Duração do vídeo todo, igual em todas as linhas dele; vazia nas copiadas antes do sinal por programa (#287)" },
  ])
}

resource "google_bigquery_dataset_iam_member" "grava_momentos" {
  for_each   = toset(["indexacao", "web"])
  dataset_id = google_bigquery_dataset.decupagens.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_service_account.mam[each.key].member
}

# A mam-terraform nasce no wizard, fora do Terraform; aqui só ganha quem a impersona.
resource "google_service_account_iam_member" "github_impersona_terraform" {
  service_account_id = "projects/${var.projeto}/serviceAccounts/mam-terraform@${var.projeto}.iam.gserviceaccount.com"
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${local.repositorio_github_id}"
}

locals {
  # Com o balanceador, o domínio entra junto das URLs do Cloud Run no CORS da quarentena.
  origens_da_aplicacao = concat(google_cloud_run_v2_service.web.urls, local.balanceador ? ["https://${var.dominio}"] : [])
}

resource "google_cloud_run_v2_service" "web" {
  name                = "mam-web"
  location            = var.regiao
  deletion_protection = false
  # Com o balanceador, só ele e o tráfego interno chegam ao serviço; sem ele, o run.app.
  ingress = local.balanceador ? "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" : "INGRESS_TRAFFIC_ALL"
  template {
    service_account = google_service_account.mam["web"].email
    scaling {
      max_instance_count = 2
    }
    containers {
      image = var.imagem
      # Liga o verificador de token do Identity Platform na API (api/main.py).
      env {
        name  = "GCP_PROJECT_ID"
        value = var.projeto
      }
      # Onde vão os eventos de uso (api/eventos_de_uso.py), em eventos_de_uso.tf.
      env {
        name  = "PUBSUB_TOPICO_USO"
        value = google_pubsub_topic.eventos_de_uso.id
      }
      # Pelo local e não pelo recurso: o CORS da quarentena aponta para este
      # serviço, e a referência ao recurso fecharia um ciclo.
      env {
        name  = "BUCKET_QUARENTENA"
        value = local.buckets["quarentena"]
      }
      env {
        name  = "BUCKET_ACEITOS"
        value = local.buckets["aceitos"]
      }
      env {
        name  = "BUCKET_DECUPAGENS"
        value = local.buckets["decupagens"]
      }
      env {
        name  = "BUCKET_REFERENCIAS"
        value = local.buckets["referencias"]
      }
      # O workflow que o reprocessar dispara (api/nuvem.py). Pelo local e não pelo
      # recurso: o workflow depende dos Jobs, que dependem do IAM dos buckets, e a
      # quarentena aponta para este serviço no CORS; a referência fecharia um ciclo.
      env {
        name  = "WORKFLOW_VALIDACAO"
        value = local.workflow_validacao
      }
      env {
        name  = "WORKFLOW_REGIAO"
        value = var.regiao
      }
      env {
        name  = "PURGA_LOGIN_RECENTE_MIN"
        value = tostring(var.minutos_do_login_recente)
      }
      env {
        name  = "BUSCA_REGIAO"
        value = var.regiao_da_busca
      }
      env {
        name  = "BUSCA_COLECAO"
        value = local.colecao_da_busca
      }
      env {
        name  = "BUSCA_INDICE_DESCRICAO"
        value = local.indice_da_descricao
      }
      env {
        name  = "BUSCA_INDICE_QUADRO"
        value = local.indice_do_quadro_em_uso
      }
      env {
        name  = "BUSCA_DIMENSAO"
        value = tostring(var.dimensao_dos_vetores)
      }
      env {
        name  = "BIGQUERY_DATASET"
        value = local.dataset_do_bigquery
      }
      env {
        name  = "BIGQUERY_TABELA"
        value = local.tabela_de_momentos
      }
      env {
        name  = "BIGQUERY_REGIAO"
        value = var.regiao_do_bigquery
      }
      # As tabelas resumidas que o painel da diretoria lê (resumos_de_uso.tf, #282).
      env {
        name  = "PAINEL_TABELA_POR_DIA_E_USUARIO"
        value = local.tabelas_do_painel_na_web.por_dia_e_usuario
      }
      env {
        name  = "PAINEL_TABELA_POR_DIA_E_PROGRAMA"
        value = local.tabelas_do_painel_na_web.por_dia_e_programa
      }
      env {
        name  = "PAINEL_TABELA_CORRECOES_POR_DIA"
        value = local.tabelas_do_painel_na_web.correcoes_por_dia
      }
      env {
        name  = "PAINEL_TABELA_CHAMADAS_POR_DIA"
        value = local.tabelas_do_painel_na_web.chamadas_por_dia
      }
      # A exportação do faturamento que o painel de custo lê (faturamento.tf, #285).
      env {
        name  = "FATURAMENTO_DATASET"
        value = google_bigquery_dataset.faturamento.dataset_id
      }
      env {
        name  = "FATURAMENTO_TABELA"
        value = "gcp_billing_export_resource_v1_*"
      }
      env {
        name  = "BUSCA_DISTANCIA_MAXIMA"
        value = tostring(var.busca_distancia_maxima)
      }
      env {
        name  = "BUSCA_PALAVRAS_MINIMAS"
        value = tostring(var.busca_palavras_minimas)
      }
      env {
        name  = "MODEL_ARMOR_MODELO"
        value = google_model_armor_template.consulta_da_busca.template_id
      }
      env {
        name  = "MODEL_ARMOR_REGIAO"
        value = google_model_armor_template.consulta_da_busca.location
      }
      env {
        name  = "RANKING_CONFIG"
        value = local.config_da_ranking
      }
      # Quem tem esses e-mails (verificados) é Administrador (api/papeis.py).
      env {
        name  = "ADMINS_EMERGENCIA"
        value = var.admins_emergencia
      }
      # A chave MAC do Cloud KMS que faz o hash das chaves de API (api/mac_kms.py).
      env {
        name  = "KMS_CHAVE_MAC"
        value = google_kms_crypto_key.chaves_de_api.id
      }
    }
  }
  depends_on = [google_project_service.apis]
}

# Rede dos Jobs de validação, transcrição, OCR e quadros-chave: sem IP externo e sem Cloud
# NAT, o arquivo hostil e o áudio não alcançam a internet, só o Storage e o Firestore (pelo acesso privado do Google).
resource "google_compute_network" "validacao" {
  name                    = "mam-validacao"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "validacao" {
  name                     = "mam-validacao"
  region                   = var.regiao
  network                  = google_compute_network.validacao.id
  ip_cidr_range            = "10.10.0.0/24"
  private_ip_google_access = true
}

# A sub-rede dos Jobs com GPU, na mesma rede: sem IP externo e sem Cloud NAT, só o Storage
# e o Firestore pelo acesso privado do Google. Faixa que não se sobrepõe à de cima.
resource "google_compute_subnetwork" "validacao_gpu" {
  name                     = "mam-validacao-gpu"
  region                   = var.regiao_gpu
  network                  = google_compute_network.validacao.id
  ip_cidr_range            = "10.20.0.0/24"
  private_ip_google_access = true
}

# O google_cloud_run_v2_job (provider 7.46) não tem sistema de arquivos só de
# leitura: isso vem da imagem, com usuário sem privilégios e só o volume em
# memória gravável (TMPDIR).
resource "google_cloud_run_v2_job" "validacao" {
  name                = "mam-validacao"
  location            = var.regiao
  deletion_protection = false
  template {
    # Um arquivo por execução.
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["validacao"].email
      # Nunca roda de novo um arquivo hostil.
      max_retries = 0
      # Medido (#135) com 120 s de vídeo sintético (854x480, H.264 a 2,3 Mbit/s e AAC,
      # com ruído e movimento) em 8 vCPU: a validação inteira levou 7,6 s, 0,063 s por
      # segundo de vídeo, ou ~910 s para 4 h. Na nuvem, com 4 vCPU, conto 3x: ~2730 s.
      # 10800 s dá 4x de folga sobre essa conta (12x sobre a medida). O teto de 7200 s de
      # cada chamada ao ffmpeg só pega um ffmpeg travado; as chamadas são em sequência, e
      # quem limita o total é este timeout.
      timeout = "10800s"
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.validacao.id
          subnetwork = google_compute_subnetwork.validacao.id
        }
      }
      containers {
        image = var.imagem_validacao
        # Onde o fim do Job vai para o webhook (api/eventos_do_job.py), em eventos.tf.
        env {
          name  = "PUBSUB_TOPICO_EVENTOS"
          value = google_pubsub_topic.eventos_do_job.id
        }
        # Onde vão os eventos de uso (api/eventos_de_uso.py), em eventos_de_uso.tf.
        env {
          name  = "PUBSUB_TOPICO_USO"
          value = google_pubsub_topic.eventos_de_uso.id
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_QUARENTENA"
          value = local.buckets["quarentena"]
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        # A única pasta gravável: o ffmpeg e o validador escrevem aqui.
        env {
          name  = "TMPDIR"
          value = "/saida"
        }
        resources {
          # ponytail: teto de 4 GiB por arquivo (TAMANHO_MAXIMO_PADRAO_BYTES), 4 h.
          # Medido (#135) em 120 s de vídeo: o proxy ficou em 51 MB (3,4 Mbit/s, com ruído,
          # então pessimista) = 5,75 GiB para 4 h; o WAV, 3,8 MB = 0,43 GiB para 4 h; o pico
          # de memória do ffmpeg, 164 MiB. O volume guarda 4 GiB da cópia limpa (o tamanho
          # do original), 5,75 do proxy e 0,43 do áudio = 10,2 GiB: volume de 12 GiB
          # (folga de 1,8). O volume em memória conta na memória do contêiner: 12 GiB mais
          # ~1 GiB do ffmpeg e do Python, e a folga até 16 GiB, o teto de 4 vCPU.
          # 4 vCPU: o proxy do clipe2 caiu 26% de 2 para 4 threads, e 8 não ganharam nada.
          limits = {
            cpu    = "4"
            memory = "16Gi"
          }
        }
        volume_mounts {
          name       = "quarentena"
          mount_path = "/quarentena"
        }
        volume_mounts {
          name       = "saida"
          mount_path = "/saida"
        }
      }
      volumes {
        name = "quarentena"
        gcs {
          bucket    = google_storage_bucket.mam["quarentena"].name
          read_only = true
        }
      }
      volumes {
        name = "saida"
        empty_dir {
          medium     = "MEMORY"
          size_limit = "12Gi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# Job de transcrição (#104): faster-whisper com o modelo da imagem, em CPU. Na mesma
# rede da validação, sem IP externo nem Cloud NAT: o áudio não alcança a internet, só o
# Storage e o Firestore (acesso privado do Google). Um vídeo por execução, e sem nova
# tentativa: a falha derruba o Job pelo ciclo de vida.
resource "google_cloud_run_v2_job" "transcricao" {
  name                = "mam-transcricao"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["transcricao"].email
      max_retries     = 0
      # NÃO medido (#135): o faster-whisper e o modelo só existem na imagem, e não há
      # imagem nem rede onde este ticket foi feito. Estimativa: o large-v3-turbo em int8,
      # em 8 vCPU, roda entre 0,5x e 1x o tempo real; 4 h de áudio levam de 2 h a 4 h.
      # 21600 s (6 h) dá 1,5x de folga sobre o pior caso. Meça no dev com um programa
      # de 4 h e ajuste (o conector do passo `transcreve` acompanha: 300 s a mais).
      timeout = "21600s"
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.validacao.id
          subnetwork = google_compute_subnetwork.validacao.id
        }
      }
      containers {
        image = var.imagem_transcricao
        # Onde o fim do Job vai para o webhook (api/eventos_do_job.py), em eventos.tf.
        env {
          name  = "PUBSUB_TOPICO_EVENTOS"
          value = google_pubsub_topic.eventos_do_job.id
        }
        # Onde vão os eventos de uso (api/eventos_de_uso.py), em eventos_de_uso.tf.
        env {
          name  = "PUBSUB_TOPICO_USO"
          value = google_pubsub_topic.eventos_de_uso.id
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        # O áudio baixado vai para o volume em memória.
        env {
          name  = "TMPDIR"
          value = "/saida"
        }
        resources {
          # O modelo large-v3-turbo em int8 cabe em poucos GiB. O áudio de 4 h em WAV mono
          # de 16 kHz tem 0,43 GiB (medido: 3,8 MB por 120 s) e o faster-whisper o carrega
          # inteiro em float32, ~0,9 GiB: 16 GiB sobram.
          limits = {
            cpu    = "8"
            memory = "16Gi"
          }
        }
        volume_mounts {
          name       = "saida"
          mount_path = "/saida"
        }
      }
      volumes {
        name = "saida"
        empty_dir {
          medium     = "MEMORY"
          size_limit = "2Gi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# Job de OCR da tela (#106): PaddleOCR com os modelos da imagem, em CPU, lendo um quadro
# por segundo do proxy. Na mesma rede da validação, sem IP externo nem Cloud NAT: o vídeo
# não alcança a internet, só o Storage e o Firestore (acesso privado do Google). Um vídeo por execução, e sem nova
# tentativa: a falha derruba o Job pelo ciclo de vida.
resource "google_cloud_run_v2_job" "ocr" {
  name                = "mam-ocr"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["ocr"].email
      max_retries     = 0
      # NÃO medido (#135): o PaddleOCR e os modelos só existem na imagem. Estimativa: o
      # detector server em CPU de 8 vCPU lê um quadro de 480p em 0,3 s a 1,5 s; 4 h são
      # 14.400 quadros, de 1,2 h a 6 h. 28800 s (8 h) dá 1,3x de folga sobre o pior caso.
      # A extração dos quadros pelo ffmpeg é desprezível (120 s de vídeo em 2 s). Meça no
      # dev com um programa de 4 h (o conector do passo `le_a_tela` acompanha).
      timeout = "28800s"
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.validacao.id
          subnetwork = google_compute_subnetwork.validacao.id
        }
      }
      containers {
        image = var.imagem_ocr
        # Onde o fim do Job vai para o webhook (api/eventos_do_job.py), em eventos.tf.
        env {
          name  = "PUBSUB_TOPICO_EVENTOS"
          value = google_pubsub_topic.eventos_do_job.id
        }
        # Onde vão os eventos de uso (api/eventos_de_uso.py), em eventos_de_uso.tf.
        env {
          name  = "PUBSUB_TOPICO_USO"
          value = google_pubsub_topic.eventos_de_uso.id
        }
        env {
          name  = "LIMIAR_DE_MUDANCA"
          value = tostring(var.limiar_de_mudanca_do_ocr)
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        # O proxy baixado e os quadros de um trecho vão para o volume em memória; o Paddle grava o cache no HOME (/saida).
        env {
          name  = "TMPDIR"
          value = "/saida"
        }
        resources {
          # Os modelos do PaddleOCR em CPU. No volume: o proxy de 4 h, 5,75 GiB (medido, com
          # ruído: pessimista), e os quadros de um trecho de 600 s, que se apagam antes do
          # trecho seguinte (api/quadros.py): 600 PNG de 367 KB (medidos, 854x480 com
          # ruído) = 0,21 GiB. Com o cache do Paddle, ~6,5 GiB: volume de 8 GiB. Os 14.400
          # quadros juntos seriam 5 GiB a mais e não caberiam. Memória: os 8 GiB do volume
          # mais ~4 GiB do Paddle e do Python, e a folga até 16 GiB.
          limits = {
            cpu    = "8"
            memory = "16Gi"
          }
        }
        volume_mounts {
          name       = "saida"
          mount_path = "/saida"
        }
      }
      volumes {
        name = "saida"
        empty_dir {
          medium     = "MEMORY"
          size_limit = "8Gi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# Job de transcrição com GPU L4 (E1, ADR 0007): a mesma lógica do Job em CPU, na região da
# GPU. Lê o áudio do bucket de aceitos (São Paulo), grava a transcrição lá, e nada fica em
# us-east4: os arquivos locais vivem no volume em memória. O Job em CPU continua como plano B.
resource "google_cloud_run_v2_job" "transcricao_gpu" {
  name                = "mam-transcricao-gpu"
  location            = var.regiao_gpu
  deletion_protection = false
  # Job com GPU e timeout acima de 1 h ("Long running GPU jobs") só existe em BETA: sem
  # isto, a API recusa a criação (deploy de 2026-11-03).
  launch_stage = "BETA"
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["transcricao"].email
      max_retries     = 0
      # NÃO medido (#240). Pior caso: a GPU não ser mais rápida que a CPU. A CPU de 8 vCPU
      # medida (FAMA, 49 min de áudio em 24 min 46 s) roda a 0,5x o tempo real: 4 h de áudio
      # levam 2 h. Mais 1,5x de folga: 10800 s (3 h). A L4 em float16 deve fazer em minutos;
      # o #240 mede e reduz (o conector do passo no Workflows, #239, acompanha).
      timeout                       = "10800s"
      gpu_zonal_redundancy_disabled = true
      node_selector {
        accelerator = "nvidia-l4"
      }
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.validacao.id
          subnetwork = google_compute_subnetwork.validacao_gpu.id
        }
      }
      containers {
        image = var.imagem_transcricao_gpu
        # Onde o fim do Job vai para o webhook (api/eventos_do_job.py), em eventos.tf.
        env {
          name  = "PUBSUB_TOPICO_EVENTOS"
          value = google_pubsub_topic.eventos_do_job.id
        }
        # Onde vão os eventos de uso (api/eventos_de_uso.py), em eventos_de_uso.tf.
        env {
          name  = "PUBSUB_TOPICO_USO"
          value = google_pubsub_topic.eventos_de_uso.id
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        env {
          name  = "TMPDIR"
          value = "/saida"
        }
        env {
          name  = "DISPOSITIVO"
          value = "gpu"
        }
        resources {
          # O mínimo do Cloud Run com GPU: 4 CPUs e 16 GiB. O modelo roda na GPU e o áudio
          # de 4 h em WAV mono de 16 kHz tem 0,43 GiB (0,9 GiB em float32): 16 GiB sobram.
          limits = {
            cpu              = "4"
            memory           = "16Gi"
            "nvidia.com/gpu" = "1"
          }
        }
        volume_mounts {
          name       = "saida"
          mount_path = "/saida"
        }
      }
      volumes {
        name = "saida"
        empty_dir {
          medium     = "MEMORY"
          size_limit = "2Gi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# Job de OCR da tela com GPU L4 (E1, ADR 0007): a mesma lógica do Job em CPU, na região da
# GPU, lendo o proxy do bucket de aceitos (São Paulo) e gravando a leitura lá. O Job em CPU
# continua como plano B.
resource "google_cloud_run_v2_job" "ocr_gpu" {
  name                = "mam-ocr-gpu"
  location            = var.regiao_gpu
  deletion_protection = false
  # Job com GPU e timeout acima de 1 h ("Long running GPU jobs") só existe em BETA: sem
  # isto, a API recusa a criação (deploy de 2026-11-03).
  launch_stage = "BETA"
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["ocr"].email
      max_retries     = 0
      # NÃO medido (#240). Pior caso: a GPU não ser mais rápida que a CPU. A CPU de 8 vCPU
      # medida (FAMA, 49 min de programa em 49 min 01 s) lê a 1x o tempo real, um quadro por
      # segundo: 4 h levam 4 h. Mais 1,5x de folga: 21600 s (6 h). O #240 mede e reduz.
      timeout                       = "21600s"
      gpu_zonal_redundancy_disabled = true
      node_selector {
        accelerator = "nvidia-l4"
      }
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.validacao.id
          subnetwork = google_compute_subnetwork.validacao_gpu.id
        }
      }
      containers {
        image = var.imagem_ocr_gpu
        # Onde o fim do Job vai para o webhook (api/eventos_do_job.py), em eventos.tf.
        env {
          name  = "PUBSUB_TOPICO_EVENTOS"
          value = google_pubsub_topic.eventos_do_job.id
        }
        # Onde vão os eventos de uso (api/eventos_de_uso.py), em eventos_de_uso.tf.
        env {
          name  = "PUBSUB_TOPICO_USO"
          value = google_pubsub_topic.eventos_de_uso.id
        }
        env {
          name  = "LIMIAR_DE_MUDANCA"
          value = tostring(var.limiar_de_mudanca_do_ocr)
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        env {
          name  = "TMPDIR"
          value = "/saida"
        }
        env {
          name  = "DISPOSITIVO"
          value = "gpu"
        }
        resources {
          # O mínimo do Cloud Run com GPU: 4 CPUs e 16 GiB. O volume em memória conta na
          # memória e continua em 8 GiB (o proxy de 4 h, 5,75 GiB, mais os quadros de um
          # trecho e o cache do Paddle, ~6,5 GiB; ver o Job em CPU). Sobram 8 GiB para o
          # Python, o Paddle e o contexto CUDA no lado da CPU (~4 a 5 GiB): cabe.
          limits = {
            cpu              = "4"
            memory           = "16Gi"
            "nvidia.com/gpu" = "1"
          }
        }
        volume_mounts {
          name       = "saida"
          mount_path = "/saida"
        }
      }
      volumes {
        name = "saida"
        empty_dir {
          medium     = "MEMORY"
          size_limit = "8Gi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# Job de objetos com GPU L4 (#243): o Florence-2 lê os quadros-chave da Decupagem, no bucket
# das decupagens (São Paulo), e grava o resultado bruto ao lado. Só processamento de
# passagem na região da GPU: nada fica lá. Não tem plano B em CPU nem escreve no Firestore.
resource "google_cloud_run_v2_job" "objetos_gpu" {
  name                = "mam-objetos-gpu"
  location            = var.regiao_gpu
  deletion_protection = false
  # Job com GPU e timeout acima de 1 h ("Long running GPU jobs") só existe em BETA: sem
  # isto, a API recusa a criação (deploy de 2026-11-03).
  launch_stage = "BETA"
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["objetos"].email
      max_retries     = 0
      # NÃO medido (#240). Conta: um programa de 4 h tem ~2000 quadros-chave (1 a 3 por
      # plano), a ~3 s cada (<OD> e <DENSE_REGION_CAPTION>, 3 feixes, na L4) = ~6000 s,
      # mais a carga do modelo; vezes 1,75 de folga: 10800 s (3 h). O #240 mede e ajusta.
      timeout                       = "10800s"
      gpu_zonal_redundancy_disabled = true
      node_selector {
        accelerator = "nvidia-l4"
      }
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.validacao.id
          subnetwork = google_compute_subnetwork.validacao_gpu.id
        }
      }
      containers {
        image = var.imagem_objetos
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_DECUPAGENS"
          value = local.buckets["decupagens"]
        }
        env {
          name  = "TMPDIR"
          value = "/saida"
        }
        env {
          name  = "DISPOSITIVO"
          value = "gpu"
        }
        resources {
          # O mínimo do Cloud Run com GPU: 4 CPUs e 16 GiB. Os quadros são lidos em memória
          # (sem disco), então o volume em memória é só o TMPDIR e o HOME do Python: 2 GiB.
          # Sobram 14 GiB para o PyTorch e o contexto CUDA no lado da CPU (~4 a 5 GiB).
          limits = {
            cpu              = "4"
            memory           = "16Gi"
            "nvidia.com/gpu" = "1"
          }
        }
        volume_mounts {
          name       = "saida"
          mount_path = "/saida"
        }
      }
      volumes {
        name = "saida"
        empty_dir {
          medium     = "MEMORY"
          size_limit = "2Gi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# A orquestração roda o Job de transcrição, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_transcricao" {
  name     = google_cloud_run_v2_job.transcricao.name
  location = google_cloud_run_v2_job.transcricao.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# A orquestração roda o Job de OCR, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_ocr" {
  name     = google_cloud_run_v2_job.ocr.name
  location = google_cloud_run_v2_job.ocr.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# A orquestração roda os Jobs com GPU, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_transcricao_gpu" {
  name     = google_cloud_run_v2_job.transcricao_gpu.name
  location = google_cloud_run_v2_job.transcricao_gpu.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_ocr_gpu" {
  name     = google_cloud_run_v2_job.ocr_gpu.name
  location = google_cloud_run_v2_job.ocr_gpu.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_objetos_gpu" {
  name     = google_cloud_run_v2_job.objetos_gpu.name
  location = google_cloud_run_v2_job.objetos_gpu.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# Job do inventário de objetos em CPU (#244): lê o resultado bruto do Florence-2 (ou os
# quadros-chave, com o motor gemini) e chama o Gemini pela Vertex, sem internet (só o
# acesso privado do Google, como a identificação); regrava a Decupagem com o inventário.
# O Workflows o roda depois do Job com GPU (motor florence) ou sozinho (motor gemini).
resource "google_cloud_run_v2_job" "inventario" {
  name                = "mam-inventario"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["objetos"].email
      max_retries     = 0
      # NÃO medido: lotes de 20 planos (florence, só texto) ou de 4 planos com imagens
      # (gemini), ~190 planos por hora de vídeo; segundos por chamada. Um programa de 4 h
      # são ~760 planos: ~40 chamadas no florence, ~190 no gemini; a ~30 s cada no pior caso
      # são ~1,6 h no gemini, então 3600 s só cobrem o florence com folga: o motor gemini
      # precisa do timeout medido no dev.
      timeout = "3600s"
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.validacao.id
          subnetwork = google_compute_subnetwork.validacao.id
        }
      }
      containers {
        image   = var.imagem_validacao
        command = ["python"]
        args    = ["-m", "api.inventario_job"]
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_DECUPAGENS"
          value = local.buckets["decupagens"]
        }
        env {
          name  = "MOTOR_OBJETOS"
          value = var.motor_objetos
        }
        env {
          name  = "MODELO_OBJETOS"
          value = var.modelo_objetos
        }
        env {
          name  = "TMPDIR"
          value = "/saida"
        }
        resources {
          # Os quadros do motor gemini são lidos em memória, lote a lote (4 planos, 2 a 3
          # quadros de resolução cheia cada); o volume é só o TMPDIR.
          limits = {
            cpu    = "2"
            memory = "4Gi"
          }
        }
        volume_mounts {
          name       = "saida"
          mount_path = "/saida"
        }
      }
      volumes {
        name = "saida"
        empty_dir {
          medium     = "MEMORY"
          size_limit = "1Gi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# A orquestração roda o Job do inventário, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_inventario" {
  name     = google_cloud_run_v2_job.inventario.name
  location = google_cloud_run_v2_job.inventario.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# A orquestração roda o Job com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda" {
  name     = google_cloud_run_v2_job.validacao.name
  location = google_cloud_run_v2_job.validacao.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# Job de análise (#127): a mesma imagem do web, com outro comando. Um Job, e não um
# serviço chamado por HTTP, porque a análise de um programa de até 4 h passa do teto de
# 1800 s da chamada HTTP do Workflows; o conector do Workflows espera o Job terminar. As
# janelas rodam até `janelas_em_paralelo` ao mesmo tempo e o progresso fica gravado no
# bucket de aceitos: sem nova tentativa do Cloud Run, uma nova execução do mesmo Job retoma.
resource "google_cloud_run_v2_job" "analise" {
  name                = "mam-analise"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["analise"].email
      max_retries     = 0
      # 4 h são 48 janelas de 5 min; com `janelas_em_paralelo` = 4, 12 rodadas. Cada janela
      # desiste em 1500 s (PRAZO_DA_ANALISE_S): o pior caso é 12 x 1500 = 18000 s. 21600 s
      # (6 h) cobre o pior caso com 1,2x de folga; o caso comum, de 1 a 3 min por janela,
      # leva de 12 a 36 min. Com um paralelismo menor o pior caso sobe: refaça a conta.
      timeout = "21600s"
      containers {
        image   = var.imagem
        command = ["python"]
        args    = ["-m", "api.analise"]
        resources {
          # Sem volume: o proxy vai ao Gemini pela URI do bucket, sem baixar. Na memória
          # ficam a transcrição e a leitura da tela de 4 h (14.400 quadros), as janelas
          # concluídas e a decupagem: dezenas de MiB em JSON, algumas centenas em objetos
          # Python, mais ~300 MiB do Python e dos clientes do Google. NÃO medido (#135):
          # 2 GiB dá ~3x de folga sobre essa conta; o padrão do Cloud Run, 512 MiB, não.
          # 1 vCPU: o trabalho é esperar o Gemini.
          limits = {
            cpu    = "1"
            memory = "2Gi"
          }
        }
        # Onde o fim do Job vai para o webhook (api/eventos_do_job.py), em eventos.tf.
        env {
          name  = "PUBSUB_TOPICO_EVENTOS"
          value = google_pubsub_topic.eventos_do_job.id
        }
        # Onde vão os eventos de uso (api/eventos_de_uso.py), em eventos_de_uso.tf.
        env {
          name  = "PUBSUB_TOPICO_USO"
          value = google_pubsub_topic.eventos_de_uso.id
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        env {
          name  = "BUCKET_DECUPAGENS"
          value = local.buckets["decupagens"]
        }
        env {
          name  = "JANELAS_EM_PARALELO"
          value = tostring(var.janelas_em_paralelo)
        }
        env {
          name  = "TOLERANCIA_DA_FALA_MS"
          value = tostring(var.tolerancia_da_fala_ms)
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# A orquestração roda o Job de análise, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_analise" {
  name     = google_cloud_run_v2_job.analise.name
  location = google_cloud_run_v2_job.analise.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# Job dos quadros-chave (#115): a imagem da validação (ffmpeg) com outro comando, na mesma
# rede, sem internet. Baixa a cópia limpa, tira um JPEG por plano, aparição e objeto e
# regrava a decupagem com o campo `quadro`. Roda depois da análise, com o Job `concluido`.
resource "google_cloud_run_v2_job" "quadros" {
  name                = "mam-quadros"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["quadros"].email
      max_retries     = 0
      # NÃO medido (#135): cada quadro é um `ffmpeg -ss` de uma chamada, de 0,1 s a 0,5 s
      # na cópia limpa; milhares de momentos de um programa de 4 h levam de minutos a
      # ~40 min no pior caso. 3600 s dá folga sobre isso; meça no dev com um programa de 4 h.
      timeout = "3600s"
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.validacao.id
          subnetwork = google_compute_subnetwork.validacao.id
        }
      }
      containers {
        image   = var.imagem_validacao
        command = ["python"]
        args    = ["-m", "api.quadros_chave"]
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        env {
          name  = "BUCKET_DECUPAGENS"
          value = local.buckets["decupagens"]
        }
        env {
          name  = "TMPDIR"
          value = "/saida"
        }
        resources {
          # No volume, só a cópia limpa (até 4 GiB, o tamanho do original) e um JPEG por
          # vez; 6 GiB. Memória: o volume mais ~1 GiB do ffmpeg e do Python.
          limits = {
            cpu    = "2"
            memory = "8Gi"
          }
        }
        volume_mounts {
          name       = "saida"
          mount_path = "/saida"
        }
      }
      volumes {
        name = "saida"
        empty_dir {
          medium     = "MEMORY"
          size_limit = "6Gi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# A orquestração roda o Job de quadros, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_quadros" {
  name     = google_cloud_run_v2_job.quadros.name
  location = google_cloud_run_v2_job.quadros.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# Job de indexação (#118): lê a Decupagem entregue (com as Correções em vigor), apaga e
# regrava o vídeo na coleção de momentos da busca e grava o estado no Job. Tem internet
# (sem vpc_access), porque o Agent Retrieval é uma API pública; só recebe a Decupagem já
# pronta, nunca o vídeo. Roda depois dos quadros-chave; a falha dele só fica no estado
# do Job (indexacao.estado), que `make reindexar` refaz.
resource "google_cloud_run_v2_job" "indexacao" {
  name                = "mam-indexacao"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["indexacao"].email
      max_retries     = 0
      # NÃO medido: milhares de registros em lotes de 200, uns segundos por lote.
      timeout = "1800s"
      containers {
        image   = var.imagem
        command = ["python"]
        args    = ["-m", "api.indexacao"]
        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        env {
          name  = "BUCKET_DECUPAGENS"
          value = local.buckets["decupagens"]
        }
        env {
          name  = "BUSCA_REGIAO"
          value = var.regiao_da_busca
        }
        env {
          name  = "BUSCA_COLECAO"
          value = local.colecao_da_busca
        }
        env {
          name  = "BUSCA_INDICE_DESCRICAO"
          value = local.indice_da_descricao
        }
        env {
          name  = "BUSCA_INDICE_QUADRO"
          value = local.indice_do_quadro_em_uso
        }
        env {
          name  = "BUSCA_DIMENSAO"
          value = tostring(var.dimensao_dos_vetores)
        }
        env {
          name  = "BIGQUERY_DATASET"
          value = local.dataset_do_bigquery
        }
        env {
          name  = "BIGQUERY_TABELA"
          value = local.tabela_de_momentos
        }
        env {
          name  = "BIGQUERY_REGIAO"
          value = var.regiao_do_bigquery
        }
        env {
          name  = "SINAL_VIDEOS"
          value = tostring(var.videos_do_sinal_por_programa)
        }
        env {
          name  = "SINAL_DESVIOS"
          value = tostring(var.desvios_do_sinal_por_programa)
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# A orquestração roda o Job de indexação, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_indexacao" {
  name     = google_cloud_run_v2_job.indexacao.name
  location = google_cloud_run_v2_job.indexacao.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# Job de referências de rosto (#111, ADR 0005): o único com internet (sem vpc_access),
# por isso só recebe nomes (a lista que a identificação deixou para o JOB_ID, ou NOMES em
# JSON e PROGRAMA) e nunca quadros do vídeo. Busca
# fotos pelo SerpAPI, o Gemini as confere e as guarda no bucket de referências.
# A chave do SerpAPI fica no Secret Manager: o Terraform cria o segredo vazio (aditivo,
# ADR 0002) e a versão com a chave é posta à mão; só este Job a lê.
resource "google_secret_manager_secret" "serpapi" {
  secret_id = "mam-serpapi"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "referencias_le_serpapi" {
  secret_id = google_secret_manager_secret.serpapi.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.mam["referencias"].member
}

resource "google_cloud_run_v2_job" "referencias" {
  name                = "mam-referencias"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["referencias"].email
      max_retries     = 0
      # Poucos nomes por execução: cada um é uma busca, dez miniaturas no máximo e uma chamada ao Gemini.
      timeout = "1800s"
      containers {
        image   = var.imagem
        command = ["python"]
        args    = ["-m", "api.referencias_job"]
        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_REFERENCIAS"
          value = local.buckets["referencias"]
        }
        env {
          name  = "SEGREDO_DO_SERPAPI"
          value = google_secret_manager_secret.serpapi.id
        }
        env {
          name  = "BUCKET_DECUPAGENS"
          value = local.buckets["decupagens"]
        }
        env {
          name  = "LIMITE_DE_BUSCAS_POR_VIDEO"
          value = tostring(var.limite_de_buscas_por_video)
        }
        env {
          name  = "VALIDADE_DAS_REFERENCIAS_DIAS"
          value = tostring(var.validade_das_referencias_dias)
        }
        env {
          name  = "REFERENCIAS_DO_ACERVO"
          value = var.referencias_do_acervo
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# Job de identificação pelo modelo forte (#221): a imagem da validação (ffmpeg) com outro
# comando, na mesma rede, sem internet (só o Storage, o Firestore e a Vertex pelo acesso
# privado do Google). Lê a Decupagem e a cópia limpa de um Job `concluido` e regrava a
# Decupagem com os nomes conferidos; a falha dele só fica na etapa, e o Job segue `concluido`.
# O Workflows o roda depois da análise (parte 4 do #112).
resource "google_cloud_run_v2_job" "identificacao" {
  name                = "mam-identificacao"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["identificacao"].email
      max_retries     = 0
      # NÃO medido (#135): no máximo `limite_de_pessoas_do_modelo_forte` chamadas ao Gemini
      # com 2 ou 3 quadros cada, de segundos a ~1 min, e um `ffmpeg -ss` por quadro. 3600 s
      # dão folga larga; meça no dev com um programa de 4 h.
      timeout = "3600s"
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.validacao.id
          subnetwork = google_compute_subnetwork.validacao.id
        }
      }
      containers {
        image   = var.imagem_validacao
        command = ["python"]
        args    = ["-m", "api.identificacao_job"]
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        env {
          name  = "BUCKET_DECUPAGENS"
          value = local.buckets["decupagens"]
        }
        env {
          name  = "LIMITE_DE_PESSOAS_DO_MODELO_FORTE"
          value = tostring(var.limite_de_pessoas_do_modelo_forte)
        }
        env {
          name  = "VALIDADE_DAS_REFERENCIAS_DIAS"
          value = tostring(var.validade_das_referencias_dias)
        }
        env {
          name  = "TMPDIR"
          value = "/saida"
        }
        resources {
          # No volume, só a cópia limpa (até 4 GiB) e os quadros de uma chamada; 6 GiB.
          # Memória: o volume mais ~1 GiB do ffmpeg e do Python.
          limits = {
            cpu    = "2"
            memory = "8Gi"
          }
        }
        volume_mounts {
          name       = "saida"
          mount_path = "/saida"
        }
      }
      volumes {
        name = "saida"
        empty_dir {
          medium     = "MEMORY"
          size_limit = "6Gi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# Job da comparação com as fotos de referência (#221): como o de identificação, e ainda lê
# o bucket das referências (as fotos já guardadas pelo `mam-referencias`, que é o único com
# internet). Regrava a Decupagem e grava os vereditos em `<job>.comparacao.json`.
# O Workflows o roda depois da análise (parte 4 do #112).
resource "google_cloud_run_v2_job" "comparacao" {
  name                = "mam-comparacao"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["comparacao"].email
      max_retries     = 0
      # NÃO medido (#135): por pessoa, uma chamada às cegas e 3 conferências foto a foto,
      # até `limite_de_comparacoes` pessoas; de segundos a ~2 min por pessoa no pior caso.
      # 3600 s dão folga larga; meça no dev.
      timeout = "3600s"
      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.validacao.id
          subnetwork = google_compute_subnetwork.validacao.id
        }
      }
      containers {
        image   = var.imagem_validacao
        command = ["python"]
        args    = ["-m", "api.comparacao_job"]
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        env {
          name  = "BUCKET_DECUPAGENS"
          value = local.buckets["decupagens"]
        }
        env {
          name  = "BUCKET_REFERENCIAS"
          value = local.buckets["referencias"]
        }
        env {
          name  = "LIMIAR_DA_COMPARACAO"
          value = tostring(var.limiar_da_comparacao)
        }
        env {
          name  = "LIMITE_DE_COMPARACOES"
          value = tostring(var.limite_de_comparacoes)
        }
        env {
          name  = "VALIDADE_DAS_REFERENCIAS_DIAS"
          value = tostring(var.validade_das_referencias_dias)
        }
        env {
          name  = "REFERENCIAS_DO_ACERVO"
          value = var.referencias_do_acervo
        }
        env {
          name  = "TMPDIR"
          value = "/saida"
        }
        resources {
          # No volume, só a cópia limpa (até 4 GiB) e os quadros de uma chamada; 6 GiB.
          # Memória: o volume mais ~1 GiB do ffmpeg e do Python.
          limits = {
            cpu    = "2"
            memory = "8Gi"
          }
        }
        volume_mounts {
          name       = "saida"
          mount_path = "/saida"
        }
      }
      volumes {
        name = "saida"
        empty_dir {
          medium     = "MEMORY"
          size_limit = "6Gi"
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# A orquestração roda o Job de identificacao, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_identificacao" {
  name     = google_cloud_run_v2_job.identificacao.name
  location = google_cloud_run_v2_job.identificacao.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# A orquestração roda o Job de referencias, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_referencias" {
  name     = google_cloud_run_v2_job.referencias.name
  location = google_cloud_run_v2_job.referencias.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# A orquestração roda o Job de comparacao, também com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_comparacao" {
  name     = google_cloud_run_v2_job.comparacao.name
  location = google_cloud_run_v2_job.comparacao.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# Avaliação diária por rubrica (#255): o Job lê a amostra do dia e grava as notas; o
# Cloud Scheduler o dispara todo dia. Sem rede da VPC: só fala com APIs do Google.
resource "google_cloud_run_v2_job" "avaliacao" {
  name                = "mam-avaliacao"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["avaliacao"].email
      max_retries     = 0
      # NÃO medido: 5 chamadas ao juiz por vídeo sorteado; 1800 s dão folga larga.
      timeout = "1800s"
      containers {
        image   = var.imagem_validacao
        command = ["python"]
        args    = ["-m", "api.avaliacao_job"]
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        env {
          name  = "REGIAO_DA_AVALIACAO"
          value = var.regiao_da_avaliacao
        }
        env {
          name  = "MODELO_DO_JUIZ"
          value = var.modelo_do_juiz
        }
        env {
          name  = "BUCKET_ACEITOS"
          value = local.buckets["aceitos"]
        }
        env {
          name  = "BUCKET_DECUPAGENS"
          value = local.buckets["decupagens"]
        }
        env {
          name  = "FUSO_DA_AVALIACAO"
          value = var.fuso_da_agenda
        }
        env {
          name  = "FRACAO_DA_AVALIACAO"
          value = tostring(var.fracao_da_avaliacao)
        }
        env {
          name  = "LIMIAR_DA_AVALIACAO"
          value = tostring(var.limiar_da_avaliacao)
        }
        env {
          name  = "QUEDA_MAXIMA_DA_AVALIACAO"
          value = tostring(var.queda_maxima_da_avaliacao)
        }
        env {
          name  = "JANELA_DA_AVALIACAO_DIAS"
          value = tostring(var.janela_da_avaliacao_dias)
        }
        env {
          name  = "PRECO_POR_MIL_CARACTERES"
          value = var.preco_por_mil_caracteres_da_avaliacao
        }
        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# O agendador só pode rodar este Job.
resource "google_cloud_run_v2_job_iam_member" "agendador_roda_avaliacao" {
  name     = google_cloud_run_v2_job.avaliacao.name
  location = google_cloud_run_v2_job.avaliacao.location
  role     = "roles/run.invoker"
  member   = google_service_account.mam["agendador"].member
}

resource "google_cloud_scheduler_job" "avaliacao" {
  name      = "mam-avaliacao-diaria"
  region    = var.regiao
  schedule  = var.agenda_da_avaliacao
  time_zone = var.fuso_da_agenda
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.projeto}/locations/${google_cloud_run_v2_job.avaliacao.location}/jobs/${google_cloud_run_v2_job.avaliacao.name}:run"
    oauth_token {
      service_account_email = google_service_account.mam["agendador"].email
    }
  }
  depends_on = [google_project_service.apis, google_cloud_run_v2_job_iam_member.agendador_roda_avaliacao]
}

# Amostra da fila de processamento (#288): de minuto em minuto o Job conta os Jobs em
# andamento por estado e a idade do mais antigo e loga (`api/fila_job.py`); o painel da fila
# lê esse log. Sem rede da VPC: só fala com o Firestore.
resource "google_cloud_run_v2_job" "fila" {
  name                = "mam-fila"
  location            = var.regiao
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.mam["fila"].email
      max_retries     = 0
      # Uma consulta ao Firestore; o minuto seguinte refaz a amostra.
      timeout = "120s"
      containers {
        image   = var.imagem_validacao
        command = ["python"]
        args    = ["-m", "api.fila_job"]
        env {
          name  = "GCP_PROJECT_ID"
          value = var.projeto
        }
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_job_iam_member" "agendador_roda_fila" {
  name     = google_cloud_run_v2_job.fila.name
  location = google_cloud_run_v2_job.fila.location
  role     = "roles/run.invoker"
  member   = google_service_account.mam["agendador"].member
}

resource "google_cloud_scheduler_job" "fila" {
  name      = "mam-fila-amostra"
  region    = var.regiao
  schedule  = var.agenda_da_fila
  time_zone = var.fuso_da_agenda
  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.projeto}/locations/${google_cloud_run_v2_job.fila.location}/jobs/${google_cloud_run_v2_job.fila.name}:run"
    oauth_token {
      service_account_email = google_service_account.mam["agendador"].email
    }
  }
  depends_on = [google_project_service.apis, google_cloud_run_v2_job_iam_member.agendador_roda_fila]
}

# Quarentena -> Eventarc -> Workflows -> Job de validação -> Job de transcrição -> Job de OCR -> Job de análise -> Jobs de identificação, referências e comparação -> Job de quadros -> Job de indexação.
locals {
  workflow_validacao = "mam-validacao"
}

resource "google_workflows_workflow" "validacao" {
  name            = local.workflow_validacao
  region          = var.regiao
  service_account = google_service_account.mam["orquestracao"].id
  source_contents = templatefile("${path.module}/validacao.workflow.yaml", {
    projeto                = var.projeto
    regiao                 = var.regiao
    job_de_validacao       = google_cloud_run_v2_job.validacao.name
    job_de_transcricao     = google_cloud_run_v2_job.transcricao.name
    job_de_ocr             = google_cloud_run_v2_job.ocr.name
    regiao_gpu             = var.regiao_gpu
    gpu_espera_total_s     = var.espera_gpu_minutos * 60
    gpu_espera_s           = var.gpu_espera_s
    gpu_fator_da_espera    = var.gpu_fator_da_espera
    gpu_espera_maxima_s    = var.gpu_espera_maxima_s
    job_de_transcricao_gpu = google_cloud_run_v2_job.transcricao_gpu.name
    job_de_ocr_gpu         = google_cloud_run_v2_job.ocr_gpu.name
    job_de_objetos_gpu     = google_cloud_run_v2_job.objetos_gpu.name
    motor_objetos          = var.motor_objetos
    job_de_inventario      = google_cloud_run_v2_job.inventario.name
    job_de_analise         = google_cloud_run_v2_job.analise.name
    job_de_identificacao   = google_cloud_run_v2_job.identificacao.name
    job_de_referencias     = google_cloud_run_v2_job.referencias.name
    job_de_comparacao      = google_cloud_run_v2_job.comparacao.name
    job_de_quadros         = google_cloud_run_v2_job.quadros.name
    job_de_indexacao       = google_cloud_run_v2_job.indexacao.name
  })
  depends_on = [google_project_service.apis]
}

# O agente de serviço do Storage publica o evento no Pub/Sub, que o Eventarc usa.
data "google_storage_project_service_account" "storage" {}

resource "google_project_iam_member" "storage_publica_eventos" {
  project = var.projeto
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.storage.email_address}"
}

# Na região da quarentena: var.regiao, porque o location do bucket volta em
# maiúsculas do provider, e o Eventarc quer a região em minúsculas.
resource "google_eventarc_trigger" "quarentena" {
  name            = "mam-quarentena-finalizada"
  location        = var.regiao
  service_account = google_service_account.mam["orquestracao"].email
  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }
  matching_criteria {
    attribute = "bucket"
    value     = google_storage_bucket.mam["quarentena"].name
  }
  destination {
    workflow = google_workflows_workflow.validacao.id
  }
  depends_on = [google_project_iam_member.storage_publica_eventos, google_project_iam_member.mam]
}

# URL pública (o run.app ou, com `dominio`, só pelo balanceador), e a API exige o token do
# Identity Platform.
resource "google_cloud_run_v2_service_iam_member" "publico" {
  name     = google_cloud_run_v2_service.web.name
  location = google_cloud_run_v2_service.web.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Login das pessoas (#11): só contas locais, criadas por `make criar-contas`.
# O MFA fica ENABLED, e não MANDATORY, porque o MANDATORY pode barrar o primeiro
# login de quem ainda não cadastrou o autenticador, e o cadastro precisa dele. O
# MFA continua obrigatório: a API recusa todo token sem o segundo fator TOTP
# (api/auth.py). O bloqueio após tentativas erradas é nativo do Identity
# Platform e não tem configuração.
#
# Criar a config inicializa o Identity Platform, o que exige firebase.projects.update,
# que a mam-terraform não tem. Quem inicializa é o Owner, uma vez, na etapa 7 do
# scripts/wizard-gcp-dev.sh; aqui a config é importada e só atualizada.
import {
  to = google_identity_platform_config.mam
  id = "projects/${var.projeto}/config"
}

resource "google_identity_platform_config" "mam" {
  autodelete_anonymous_users = true
  sign_in {
    email {
      enabled           = true
      password_required = true
    }
    # O login por telefone fica desligado. O Google devolve este bloco com enabled=false e
    # o provider não o marca como computado: sem declará-lo, todo plan mostrava a remoção
    # do bloco e o apply "corrigia" sem mudar nada (#291).
    phone_number {
      enabled = false
    }
  }
  # Sem balanceador, a lista fica como o Google a devolve (nula aqui). Com ele, vai a lista
  # padrão do Identity Platform mais o domínio: o login só funciona nos domínios autorizados.
  authorized_domains = local.balanceador ? ["localhost", "${var.projeto}.firebaseapp.com", "${var.projeto}.web.app", var.dominio] : null
  # A chave web vai no front e é pública: sem isto, qualquer um criaria uma conta.
  client {
    permissions {
      disabled_user_signup   = true
      disabled_user_deletion = true
    }
  }
  mfa {
    state = "ENABLED"
    provider_configs {
      state = "ENABLED"
      totp_provider_config {
        # Aceita o código anterior e o seguinte, para relógio de celular adiantado ou atrasado.
        adjacent_intervals = 1
      }
    }
  }
  # Os logs de requisição alimentam o alerta de login dos administradores de emergência.
  monitoring {
    request_logging {
      enabled = true
    }
  }
  depends_on = [google_project_service.apis]
}

# O provider não tem a política de senha (passwordPolicyConfig), então ela vai
# pela API REST, de novo a cada mudança. Roda na máquina do `make deploy-dev`,
# como a mam-terraform.
locals {
  politica_de_senha = jsonencode({
    passwordPolicyConfig = {
      passwordPolicyEnforcementState = "ENFORCE"
      forceUpgradeOnSignin           = true
      passwordPolicyVersions = [{
        customStrengthOptions = {
          minPasswordLength                = 12
          containsLowercaseCharacter       = true
          containsUppercaseCharacter       = true
          containsNumericCharacter         = true
          containsNonAlphanumericCharacter = true
        }
      }]
    }
  })
}

resource "terraform_data" "politica_de_senha" {
  triggers_replace = [local.politica_de_senha]
  provisioner "local-exec" {
    command = <<-EOT
      curl -sSf -o /dev/null -X PATCH \
        "https://identitytoolkit.googleapis.com/admin/v2/projects/${var.projeto}/config?updateMask=passwordPolicyConfig" \
        -H "Authorization: Bearer $(gcloud auth print-access-token --impersonate-service-account "$GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")" \
        -H "x-goog-user-project: ${var.projeto}" \
        -H "Content-Type: application/json" \
        -d '${local.politica_de_senha}'
    EOT
  }
  depends_on = [google_identity_platform_config.mam]
}

# Alerta a cada login de administrador de emergência, para os próprios
# administradores: cada um vê também os logins do outro. Casa o passo da senha,
# o único que traz o e-mail no log, então também avisa de senha errada. O e-mail
# é buscado no texto do log, e não num campo, para o alerta não ficar mudo se o
# formato do log mudar.
locals {
  admins_emergencia = [for email in split(",", var.admins_emergencia) : trimspace(email)]
}

resource "google_monitoring_notification_channel" "admin_emergencia" {
  for_each     = toset(local.admins_emergencia)
  display_name = "Administrador de emergência ${each.key}"
  type         = "email"
  labels       = { email_address = each.key }
  depends_on   = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "login_admin_emergencia" {
  display_name = "Login de administrador de emergência"
  combiner     = "OR"
  conditions {
    display_name = "Login de administrador de emergência"
    condition_matched_log {
      filter = join("\n", [
        "resource.type=\"identitytoolkit_project\"",
        "jsonPayload.methodName:\"SignInWithPassword\"",
        "(${join(" OR ", [for email in local.admins_emergencia : "\"${email}\""])})",
      ])
    }
  }
  # Alerta de log exige limite: no máximo um aviso a cada 5 min.
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }
  notification_channels = [for canal in google_monitoring_notification_channel.admin_emergencia : canal.id]
  documentation {
    content = "Uma conta de administrador de emergência tentou entrar no MAM. Se não foi você nem o outro administrador, troque a senha e o autenticador da conta."
  }
  depends_on = [google_identity_platform_config.mam]
}

# Sinais de qualidade em produção (#286). Os jobs escrevem uma linha JSON por evento
# (`api/sinais.py`; a queda da avaliação sai de `api/avaliacao.py`) e o Cloud Run a lê como
# `jsonPayload`; a falha da execução de uma etapa sai do Workflows (`marca_fim`). Os nomes
# dos campos e dos eventos são o contrato com o código: mudar um lá pede mudar o filtro
# aqui (um teste confere). Cada percentual vira uma métrica de distribuição, e o alerta
# olha a média na janela; as contagens contam linhas.
locals {
  janela_dos_alertas_s = "${var.janela_dos_alertas_horas * 3600}s"
  canais_de_alerta     = [for canal in google_monitoring_notification_channel.admin_emergencia : canal.id]
  filtro_video_concluido = join(" AND ", [
    "resource.type=\"cloud_run_job\"",
    "jsonPayload.evento=\"video_concluido\"",
  ])
  sinais_percentuais = {
    escalonadas = {
      campo     = "pct_escalonadas"
      limiar    = var.limiar_de_escalonadas_pct
      titulo    = "Janelas escalonadas para o 3.8 Flash acima do limiar"
      documento = "A média do percentual de janelas reanalisadas pelo 3.8 Flash passou do limiar. Ou a primeira passada está deixando mais dúvidas (modelo ou prompt mudou?), ou a fração da amostra de controle subiu."
    }
    nao_identificadas = {
      campo     = "pct_nao_identificadas"
      limiar    = var.limiar_de_nao_identificadas_pct
      titulo    = "Pessoas não identificadas acima do limiar"
      documento = "A média do percentual de pessoas na imagem sem nome passou do limiar. Confira o catálogo do programa, as fotos de referência e a transcrição dos vídeos recentes."
    }
  }
}

resource "google_logging_metric" "sinal_percentual" {
  for_each        = local.sinais_percentuais
  name            = "mam_pct_${each.key}"
  description     = "Percentual ${each.value.campo} por vídeo concluído (log video_concluido)"
  filter          = local.filtro_video_concluido
  value_extractor = "EXTRACT(jsonPayload.${each.value.campo})"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "%"
  }
  bucket_options {
    linear_buckets {
      num_finite_buckets = 20
      width              = 5
      offset             = 0
    }
  }
  depends_on = [google_project_service.apis]
}

# Uma linha por resposta recusada, de qualquer chamada ao modelo (também do vídeo que
# falhou). O contador conta as linhas (o `value_extractor` é das métricas de distribuição);
# o total por vídeo, no log `video_concluido`, fica para a consulta.
resource "google_logging_metric" "respostas_fora_do_esquema" {
  name        = "mam_respostas_fora_do_esquema"
  description = "Respostas do modelo recusadas pelo esquema (e refeitas)"
  filter = join(" AND ", [
    "resource.type=\"cloud_run_job\"",
    "jsonPayload.evento=\"resposta_fora_do_esquema\"",
  ])
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
  depends_on = [google_project_service.apis]
}

resource "google_logging_metric" "falhas_por_etapa" {
  name        = "mam_falhas_por_etapa"
  description = "Falhas de etapa do processamento, com a etapa como rótulo"
  # Do Job, a falha que ele trata; do Workflows, a execução que falhou.
  filter = join(" AND ", [
    "(resource.type=\"cloud_run_job\" OR resource.type=\"workflows.googleapis.com/Workflow\")",
    "jsonPayload.evento=\"falha_de_etapa\"",
  ])
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "etapa"
      value_type  = "STRING"
      description = "Etapa que falhou"
    }
  }
  label_extractors = {
    etapa = "EXTRACT(jsonPayload.etapa)"
  }
  depends_on = [google_project_service.apis]
}

resource "google_logging_metric" "queda_da_avaliacao" {
  name        = "mam_queda_da_avaliacao"
  description = "Quedas da avaliação por rubrica (#255), com o requisito como rótulo"
  filter = join(" AND ", [
    "resource.type=\"cloud_run_job\"",
    "jsonPayload.evento=\"queda_de_qualidade\"",
  ])
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "requisito"
      value_type  = "STRING"
      description = "Requisito da rubrica que caiu"
    }
  }
  label_extractors = {
    requisito = "EXTRACT(jsonPayload.requisito)"
  }
  depends_on = [google_project_service.apis]
}

resource "google_logging_metric" "desvio_de_programa" {
  name        = "mam_desvio_de_programa"
  description = "Vídeos com eventos por hora fora da média do programa (#287), com o tipo de evento como rótulo"
  filter = join(" AND ", [
    "resource.type=\"cloud_run_job\"",
    "jsonPayload.evento=\"desvio_de_programa\"",
  ])
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "tipo"
      value_type  = "STRING"
      description = "aparicoes, mencoes, pautas ou comerciais"
    }
    labels {
      key         = "programa"
      value_type  = "STRING"
      description = "Programa do vídeo"
    }
  }
  label_extractors = {
    tipo     = "EXTRACT(jsonPayload.tipo)"
    programa = "EXTRACT(jsonPayload.programa)"
  }
  depends_on = [google_project_service.apis]
}

# Os avisos de métrica não têm limite de repetição como os de log: o `auto_close` fecha o
# incidente quando a janela volta ao normal.
resource "google_monitoring_alert_policy" "sinal_percentual" {
  for_each     = local.sinais_percentuais
  display_name = each.value.titulo
  combiner     = "OR"
  conditions {
    display_name = each.value.titulo
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.sinal_percentual[each.key].name}\" AND resource.type=\"cloud_run_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = each.value.limiar
      duration        = "0s"
      # Métrica de distribuição: o ALIGN_MEAN não se aplica a ela (a API recusa); o
      # ALIGN_DELTA junta os valores da janela e o REDUCE_MEAN dá a média deles.
      aggregations {
        alignment_period     = local.janela_dos_alertas_s
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_MEAN"
      }
    }
  }
  alert_strategy {
    auto_close = "1800s"
  }
  notification_channels = local.canais_de_alerta
  documentation {
    content = each.value.documento
  }
  # A métrica de log recém-criada demora a aparecer para o Monitoring (espera_das_metricas.tf).
  depends_on = [time_sleep.metricas_dos_alertas]
}

resource "google_monitoring_alert_policy" "fora_do_esquema" {
  display_name = "Respostas fora do esquema acima do limiar"
  combiner     = "OR"
  conditions {
    display_name = "Respostas fora do esquema acima do limiar"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.respostas_fora_do_esquema.name}\" AND resource.type=\"cloud_run_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.limiar_de_fora_do_esquema
      duration        = "0s"
      aggregations {
        alignment_period     = local.janela_dos_alertas_s
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }
  alert_strategy {
    auto_close = "1800s"
  }
  notification_channels = local.canais_de_alerta
  documentation {
    content = "O Gemini devolveu mais respostas fora do esquema (refeitas) do que o limiar na janela. Suspeite de mudança do modelo ou do prompt; as respostas refeitas custam chamadas a mais."
  }
  # A métrica de log recém-criada demora a aparecer para o Monitoring (espera_das_metricas.tf).
  depends_on = [time_sleep.metricas_dos_alertas]
}

resource "google_monitoring_alert_policy" "falhas_por_etapa" {
  display_name = "Falhas de uma etapa acima do limite"
  combiner     = "OR"
  # O filtro de um alerta precisa de um resource.type (a API recusa sem ele), e a métrica
  # vem de dois: uma condição para cada, e o limite vale por origem. Somar as duas pediria
  # um filtro com one_of ou PromQL, não validados na API (deploy de 2026-11-03).
  dynamic "conditions" {
    for_each = {
      Jobs      = "cloud_run_job"
      Workflows = "workflows.googleapis.com/Workflow"
    }
    content {
      display_name = "Falhas de uma etapa acima do limite (${conditions.key})"
      condition_threshold {
        filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.falhas_por_etapa.name}\" AND resource.type=\"${conditions.value}\""
        comparison      = "COMPARISON_GT"
        threshold_value = var.limite_de_falhas_por_etapa
        duration        = "0s"
        aggregations {
          alignment_period     = local.janela_dos_alertas_s
          per_series_aligner   = "ALIGN_DELTA"
          cross_series_reducer = "REDUCE_SUM"
          group_by_fields      = ["metric.label.etapa"]
        }
      }
    }
  }
  alert_strategy {
    auto_close = "1800s"
  }
  notification_channels = local.canais_de_alerta
  documentation {
    content = "Uma etapa do processamento falhou mais vezes do que o limite na janela; o rótulo `etapa` diz qual. O log `falha_de_etapa` traz o job e o motivo."
  }
  # A métrica de log recém-criada demora a aparecer para o Monitoring (espera_das_metricas.tf).
  depends_on = [time_sleep.metricas_dos_alertas]
}

resource "google_monitoring_alert_policy" "queda_da_avaliacao" {
  display_name = "Queda na avaliação por rubrica"
  combiner     = "OR"
  conditions {
    display_name = "Queda na avaliação por rubrica"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.queda_da_avaliacao.name}\" AND resource.type=\"cloud_run_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period     = local.janela_dos_alertas_s
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.label.requisito"]
      }
    }
  }
  alert_strategy {
    auto_close = "1800s"
  }
  notification_channels = local.canais_de_alerta
  documentation {
    content = "A avaliação diária por rubrica (#255) achou um requisito abaixo do limiar ou em queda frente à média dos dias anteriores. O rótulo `requisito` diz qual; o log `queda_de_qualidade` traz as notas."
  }
  # A métrica de log recém-criada demora a aparecer para o Monitoring (espera_das_metricas.tf).
  depends_on = [time_sleep.metricas_dos_alertas]
}

resource "google_monitoring_alert_policy" "desvio_de_programa" {
  display_name = "Vídeo fora da média do programa"
  combiner     = "OR"
  conditions {
    display_name = "Vídeo fora da média do programa"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.desvio_de_programa.name}\" AND resource.type=\"cloud_run_job\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period     = local.janela_dos_alertas_s
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.label.programa", "metric.label.tipo"]
      }
    }
  }
  alert_strategy {
    auto_close = "1800s"
  }
  notification_channels = local.canais_de_alerta
  documentation {
    content = "Um vídeo concluído tem aparições, menções, pautas ou comerciais por hora de vídeo a mais de K desvios da média dos últimos N vídeos do mesmo programa (K e N são variáveis do Terraform). Os rótulos dizem o programa e o tipo; o log `desvio_de_programa` traz o job, o valor, a média e o desvio. Pode ser um programa diferente do normal ou uma decupagem ruim: abra o vídeo."
  }
  # A métrica de log recém-criada demora a aparecer para o Monitoring (espera_das_metricas.tf).
  depends_on = [time_sleep.metricas_dos_alertas]
}

# Painéis de observabilidade (#288). Cada gráfico lê uma métrica de log (os jobs e o Workflows
# escrevem uma linha JSON por evento: `api/sinais.py`, `api/fila_job.py`, `marca_fim` e
# `roda_o_job_com_gpu` do Workflows; os campos e os eventos são o contrato com os filtros
# abaixo, e um teste confere) ou uma métrica nativa do Cloud Run. As métricas de log em
# distribuição são lidas em PromQL (`_sum`, `_count`, `_bucket`); o nome é o da métrica com o
# prefixo `logging_googleapis_com:user_`.
locals {
  janela_dos_paineis = "${var.janela_dos_paineis_horas}h"
  filtro_dos_jobs    = "resource.type=\"cloud_run_job\""
  filtro_da_api = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${google_cloud_run_v2_service.web.name}\"",
    "logName:\"run.googleapis.com%2Frequests\"",
  ])
  # O mesmo serviço entrega o front em `/`: as requisições da API são só as de `/v1/`.
  filtro_das_requisicoes_da_api = "${local.filtro_da_api} AND httpRequest.requestUrl=~\"^https?://[^/]+/v1/\""
  jobs_com_gpu = [
    google_cloud_run_v2_job.transcricao_gpu.name,
    google_cloud_run_v2_job.ocr_gpu.name,
    google_cloud_run_v2_job.objetos_gpu.name,
  ]
  filtro_dos_jobs_com_gpu = "resource.type=\"cloud_run_job\" AND resource.labels.job_name=one_of(${join(",", [for j in local.jobs_com_gpu : "\"${j}\""])})"
  metrica_de_log          = { for nome in ["duracao_da_etapa", "tokens_de_entrada", "tokens_de_saida", "fila_quantidade", "fila_idade", "falta_de_gpu", "requisicoes_da_api"] : nome => "logging_googleapis_com:user_mam_${nome}" }

  # US$ na janela, por etapa: soma dos tokens de cada modelo vezes o preço dele (o `or` junta
  # as séries de modelos diferentes antes do `sum`; a etapa que não usou o modelo some).
  custo_por_etapa = {
    for sentido, metrica in { entrada = local.metrica_de_log["tokens_de_entrada"], saida = local.metrica_de_log["tokens_de_saida"] } :
    sentido => "sum by (etapa) (${join(" or ", [for modelo, preco in var.precos_por_milhao_de_tokens : "(increase(${metrica}_sum{modelo=\"${modelo}\"}[${local.janela_dos_paineis}]) * ${preco[sentido] / 1000000})"])})"
  }

  # Cada painel é uma lista de gráficos; o desenho põe dois por linha.
  graficos_dos_paineis = {
    tempo_e_custo = concat(
      [
        {
          titulo = "Tempo por etapa (p50 e p95)"
          series = [
            {
              promql  = "histogram_quantile(0.5, sum by (le, etapa) (increase(${local.metrica_de_log["duracao_da_etapa"]}_bucket[${local.janela_dos_paineis}])))"
              legenda = "p50 {{etapa}}"
            },
            {
              promql  = "histogram_quantile(0.95, sum by (le, etapa) (increase(${local.metrica_de_log["duracao_da_etapa"]}_bucket[${local.janela_dos_paineis}])))"
              legenda = "p95 {{etapa}}"
            },
          ]
          unidade = "s"
        },
        {
          titulo = "Tokens por etapa (entrada e saída)"
          series = [
            {
              promql  = "sum by (etapa) (increase(${local.metrica_de_log["tokens_de_entrada"]}_sum[${local.janela_dos_paineis}]))"
              legenda = "entrada {{etapa}}"
            },
            {
              promql  = "sum by (etapa) (increase(${local.metrica_de_log["tokens_de_saida"]}_sum[${local.janela_dos_paineis}]))"
              legenda = "saída {{etapa}}"
            },
          ]
          unidade = "1"
        },
      ],
      # Sem preço na configuração o gráfico de custo não existe: os tokens acima são o que há.
      length(var.precos_por_milhao_de_tokens) == 0 ? [] : [
        {
          titulo = "Custo por etapa (US$ na janela, tokens vezes o preço da configuração)"
          series = [
            { promql = local.custo_por_etapa["entrada"], legenda = "entrada {{etapa}}" },
            { promql = local.custo_por_etapa["saida"], legenda = "saída {{etapa}}" },
          ]
          unidade = "USD"
        },
      ],
    )
    fila = [
      {
        titulo = "Jobs em cada estado (média das amostras do minuto)"
        series = [
          {
            promql  = "sum by (estado) (increase(${local.metrica_de_log["fila_quantidade"]}_sum[10m])) / sum by (estado) (increase(${local.metrica_de_log["fila_quantidade"]}_count[10m]))"
            legenda = "{{estado}}"
          },
        ]
        unidade = "1"
      },
      {
        titulo = "Idade do Job mais antigo em andamento, por estado (média das amostras)"
        series = [
          {
            promql  = "sum by (estado) (increase(${local.metrica_de_log["fila_idade"]}_sum[10m])) / sum by (estado) (increase(${local.metrica_de_log["fila_idade"]}_count[10m]))"
            legenda = "{{estado}}"
          },
        ]
        unidade = "s"
      },
    ]
    erros_da_api = [
      {
        titulo = "Requisições com erro, por rota e código"
        series = [
          {
            promql  = "sum by (rota, codigo) (increase(${local.metrica_de_log["requisicoes_da_api"]}{codigo=~\"[45]..\"}[5m]))"
            legenda = "{{rota}} {{codigo}}"
          },
        ]
        unidade = "1"
      },
      {
        titulo = "Requisições, por rota"
        series = [
          {
            promql  = "sum by (rota) (increase(${local.metrica_de_log["requisicoes_da_api"]}[5m]))"
            legenda = "{{rota}}"
          },
        ]
        unidade = "1"
      },
      {
        titulo = "Latência da API (p50, p95 e p99)"
        series = [
          for percentil in ["50", "95", "99"] : {
            filtro  = "metric.type=\"run.googleapis.com/request_latencies\" AND resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.web.name}\""
            aligner = "ALIGN_PERCENTILE_${percentil}"
            reducer = "REDUCE_MAX"
            agrupar = []
            legenda = "p${percentil}"
          }
        ]
        unidade = "ms"
      },
    ]
    gpu = [
      {
        titulo = "Utilização da GPU (p95), por Job"
        series = [{
          filtro  = "metric.type=\"run.googleapis.com/container/gpu/utilizations\" AND ${local.filtro_dos_jobs_com_gpu}"
          aligner = "ALIGN_PERCENTILE_95"
          reducer = "REDUCE_MAX"
          agrupar = ["resource.label.job_name"]
          legenda = "$${resource.labels.job_name}"
        }]
        unidade = "%"
      },
      {
        titulo = "Memória da GPU em uso (p95), por Job"
        series = [{
          filtro  = "metric.type=\"run.googleapis.com/container/gpu/memory_usages\" AND ${local.filtro_dos_jobs_com_gpu}"
          aligner = "ALIGN_PERCENTILE_95"
          reducer = "REDUCE_MAX"
          agrupar = ["resource.label.job_name"]
          legenda = "$${resource.labels.job_name}"
        }]
        unidade = "By"
      },
      {
        titulo = "Tempo de início do contêiner (p95), por Job"
        series = [{
          filtro  = "metric.type=\"run.googleapis.com/container/startup_latencies\" AND ${local.filtro_dos_jobs_com_gpu}"
          aligner = "ALIGN_PERCENTILE_95"
          reducer = "REDUCE_MAX"
          agrupar = ["resource.label.job_name"]
          legenda = "$${resource.labels.job_name}"
        }]
        unidade = "ms"
      },
      {
        titulo = "Falta de GPU ou de cota (tentativas, por etapa)"
        series = [
          {
            promql  = "sum by (etapa) (increase(${local.metrica_de_log["falta_de_gpu"]}[${local.janela_dos_paineis}]))"
            legenda = "{{etapa}}"
          },
        ]
        unidade = "1"
      },
    ]
  }
  titulos_dos_paineis = {
    tempo_e_custo = "MAM · Tempo e custo por etapa"
    fila          = "MAM · Fila de processamento"
    erros_da_api  = "MAM · Erros e latência da API"
    gpu           = "MAM · Jobs com GPU"
  }
}

# O tempo da etapa vem do Workflows (`marca_fim`), só das etapas concluídas.
resource "google_logging_metric" "duracao_da_etapa" {
  name            = "mam_duracao_da_etapa"
  description     = "Duração das etapas concluídas, com a etapa como rótulo (#288)"
  filter          = "resource.type=\"workflows.googleapis.com/Workflow\" AND jsonPayload.evento=\"duracao_da_etapa\""
  value_extractor = "EXTRACT(jsonPayload.duracao_s)"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "s"
    labels {
      key         = "etapa"
      value_type  = "STRING"
      description = "Etapa do processamento"
    }
  }
  label_extractors = {
    etapa = "EXTRACT(jsonPayload.etapa)"
  }
  # De 1 s a cerca de 5 dias: a leitura da tela com GPU passa de horas.
  bucket_options {
    exponential_buckets {
      num_finite_buckets = 30
      growth_factor      = 1.5
      scale              = 1
    }
  }
  depends_on = [google_project_service.apis]
}

# Os tokens de cada chamada ao modelo (`uso_do_modelo`); a etapa é o Job que chamou, sem o
# `mam-` do nome, para casar com a etapa do tempo (`mam-analise` -> `analise`; só o
# `mam-inventario` fica `inventario`, e não `inventario_de_objetos`).
resource "google_logging_metric" "tokens_do_modelo" {
  for_each        = toset(["tokens_de_entrada", "tokens_de_saida"])
  name            = "mam_${each.key}"
  description     = "${each.value} por chamada ao modelo, com a etapa e o modelo como rótulos (#288)"
  filter          = "${local.filtro_dos_jobs} AND jsonPayload.evento=\"uso_do_modelo\""
  value_extractor = "EXTRACT(jsonPayload.${each.value})"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "1"
    labels {
      key         = "etapa"
      value_type  = "STRING"
      description = "Job (etapa) que chamou o modelo"
    }
    labels {
      key         = "modelo"
      value_type  = "STRING"
      description = "ID do modelo"
    }
  }
  label_extractors = {
    etapa  = "REGEXP_EXTRACT(resource.labels.job_name, \"^mam-(.+)$\")"
    modelo = "EXTRACT(jsonPayload.modelo)"
  }
  # De 1 a cerca de 4 milhões de tokens por chamada.
  bucket_options {
    exponential_buckets {
      num_finite_buckets = 44
      growth_factor      = 1.4
      scale              = 1
    }
  }
  depends_on = [google_project_service.apis]
}

# A amostra da fila (`api/fila_job.py`): uma linha por estado por minuto.
resource "google_logging_metric" "fila" {
  for_each = {
    fila_quantidade = { extrai = "quantidade", unidade = "1" }
    fila_idade      = { extrai = "idade_do_mais_antigo_s", unidade = "s" }
  }
  name            = "mam_${each.key}"
  description     = "Amostra da fila de processamento (${each.value.extrai}), com o estado como rótulo (#288)"
  filter          = "${local.filtro_dos_jobs} AND jsonPayload.evento=\"fila_de_jobs\""
  value_extractor = "EXTRACT(jsonPayload.${each.value.extrai})"
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = each.value.unidade
    labels {
      key         = "estado"
      value_type  = "STRING"
      description = "Estado do Job"
    }
  }
  label_extractors = {
    estado = "EXTRACT(jsonPayload.estado)"
  }
  # Só a média é lida (do _sum e do _count); as faixas, de 5000 em 5000, não pesam.
  bucket_options {
    linear_buckets {
      num_finite_buckets = 20
      width              = 5000
      offset             = 0
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_logging_metric" "falta_de_gpu" {
  name        = "mam_falta_de_gpu"
  description = "Tentativas que acharam o Job sem GPU ou sem cota, com a etapa como rótulo (#288)"
  filter      = "resource.type=\"workflows.googleapis.com/Workflow\" AND jsonPayload.evento=\"falta_de_gpu\""
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "etapa"
      value_type  = "STRING"
      description = "Etapa com GPU"
    }
  }
  label_extractors = {
    etapa = "EXTRACT(jsonPayload.etapa)"
  }
  depends_on = [google_project_service.apis]
}

# Uma linha por requisição da API; a rota é o recurso (`/v1/jobs`, `/v1/busca`), sem os
# ids do caminho, para a cardinalidade ficar no número de recursos.
resource "google_logging_metric" "requisicoes_da_api" {
  name        = "mam_requisicoes_da_api"
  description = "Requisições da API, com a rota (recurso de /v1) e o código HTTP como rótulos (#288)"
  filter      = local.filtro_das_requisicoes_da_api
  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "rota"
      value_type  = "STRING"
      description = "Recurso de /v1 do caminho, sem ids"
    }
    labels {
      key         = "codigo"
      value_type  = "STRING"
      description = "Código HTTP"
    }
  }
  label_extractors = {
    rota   = "REGEXP_EXTRACT(httpRequest.requestUrl, \"^https?://[^/]+(/v1/[^/?]+)\")"
    codigo = "EXTRACT(httpRequest.status)"
  }
  depends_on = [google_project_service.apis]
}

resource "google_monitoring_dashboard" "painel" {
  for_each = toset(keys(local.graficos_dos_paineis))
  dashboard_json = jsonencode({
    displayName = local.titulos_dos_paineis[each.key]
    mosaicLayout = {
      columns = 12
      tiles = [
        for i, grafico in local.graficos_dos_paineis[each.key] : {
          xPos   = (i % 2) * 6
          yPos   = floor(i / 2) * 4
          width  = 6
          height = 4
          widget = {
            title = grafico.titulo
            xyChart = {
              dataSets = [
                for serie in grafico.series : {
                  plotType       = "LINE"
                  legendTemplate = serie.legenda
                  # Uma condicional com {prometheusQuery} de um lado e {timeSeriesFilter} do
                  # outro não passa no plan (os dois lados precisam do mesmo tipo, e o
                  # validate não pega): cada lado vira um mapa, vazio quando não se aplica.
                  timeSeriesQuery = merge(
                    can(serie.promql) ? { prometheusQuery = serie.promql } : {},
                    can(serie.promql) ? {} : {
                      timeSeriesFilter = {
                        filter = serie.filtro
                        aggregation = {
                          alignmentPeriod    = "60s"
                          perSeriesAligner   = serie.aligner
                          crossSeriesReducer = serie.reducer
                          groupByFields      = serie.agrupar
                        }
                      }
                    },
                  )
                }
              ]
              yAxis = { scale = "LINEAR" }
            }
          }
        }
      ]
    }
  })
  depends_on = [
    google_logging_metric.duracao_da_etapa,
    google_logging_metric.tokens_do_modelo,
    google_logging_metric.fila,
    google_logging_metric.falta_de_gpu,
    google_logging_metric.requisicoes_da_api,
  ]
}

# Chave web do login, que vai no build do front. O provider a marca como
# sensível, mas ela é pública por natureza: o cadastro bloqueado acima é o que protege.
output "identity_api_key" {
  value     = google_identity_platform_config.mam.client[0].api_key
  sensitive = true
}

output "chave_mac_kms" {
  description = "Nome completo da chave MAC do Cloud KMS: KMS_CHAVE_MAC no `make emitir-chave`"
  value       = google_kms_crypto_key.chaves_de_api.id
}

# O endereço do MAM: o domínio, com o balanceador; sem ele, o run.app.
output "url" {
  value = local.balanceador ? "https://${var.dominio}" : google_cloud_run_v2_service.web.uri
}

# Para as ferramentas locais: o deploy-dev envia as imagens a este repositório, e o
# make gravar-cassetes sobe o clipe sintético no bucket de clipes-ouro.
output "repositorio" {
  value = "${var.regiao}-docker.pkg.dev/${var.projeto}/${google_artifact_registry_repository.mam.repository_id}"
}

# Para o deploy-dev: o repositório das imagens com GPU, que guarda também o cache delas.
output "repositorio_gpu" {
  value = "${var.regiao_gpu}-docker.pkg.dev/${var.projeto}/${google_artifact_registry_repository.mam_gpu.repository_id}"
}

# Para o Workflows (#239) e para o teste dos Jobs com GPU depois da publicação.
output "regiao_gpu" {
  value = var.regiao_gpu
}

output "job_de_transcricao_gpu" {
  value = google_cloud_run_v2_job.transcricao_gpu.name
}

output "job_de_ocr_gpu" {
  value = google_cloud_run_v2_job.ocr_gpu.name
}

output "job_de_objetos_gpu" {
  value = google_cloud_run_v2_job.objetos_gpu.name
}

output "job_de_inventario" {
  value = google_cloud_run_v2_job.inventario.name
}

output "gpu_espera_total_s" {
  value = var.espera_gpu_minutos * 60
}

output "gpu_espera_maxima_s" {
  value = var.gpu_espera_maxima_s
}

output "gpu_espera_s" {
  value = var.gpu_espera_s
}

output "gpu_fator_da_espera" {
  value = var.gpu_fator_da_espera
}

# Para o make copiar-para-bigquery.
output "bigquery_dataset" {
  value = local.dataset_do_bigquery
}

output "bigquery_tabela" {
  value = local.tabela_de_momentos
}

output "bigquery_regiao" {
  value = var.regiao_do_bigquery
}

# Para o make criar-colecao-da-busca, o make medir-busca e o make sondar-busca.
output "busca_regiao" {
  value = var.regiao_da_busca
}

output "busca_colecao" {
  value = local.colecao_da_busca
}

output "busca_colecao_de_medida" {
  value = local.colecao_de_medida_da_busca
}

output "busca_indice_descricao" {
  value = local.indice_da_descricao
}

output "busca_indice_quadro" {
  value = local.indice_do_quadro_em_uso
}

output "busca_dimensao" {
  value = var.dimensao_dos_vetores
}

# O corte do serviço, para o make sondar-busca ver o mesmo que o dev.
output "busca_distancia_maxima" {
  value = var.busca_distancia_maxima
}

output "busca_palavras_minimas" {
  value = var.busca_palavras_minimas
}

output "bucket_aceitos" {
  value = local.buckets["aceitos"]
}

output "bucket_decupagens" {
  value = local.buckets["decupagens"]
}

output "workflow_regiao" {
  value = var.regiao
}

output "workflow_validacao" {
  value = local.workflow_validacao
}

output "bucket_clipes_ouro" {
  value = local.buckets["clipes-ouro"]
}

# Para o build no Cloud Build e para a variável do CD no GitHub (README).
output "conta_build" {
  value = google_service_account.mam["build"].id
}

output "bucket_fontes" {
  value = google_storage_bucket.fontes.name
}

output "provedor_github" {
  value = google_iam_workload_identity_pool_provider.github.name
}
