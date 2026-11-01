# Infraestrutura do dev da E0 (#8). Aplicada por `make deploy-dev`, à mão ou no
# CD (#71), que impersona a conta mam-terraform. No IAM do projeto, só
# google_project_iam_member, que é aditivo (ADR 0002).

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

variable "dimensao_dos_vetores" {
  description = "Dimensão dos vetores da busca; fixa na criação da coleção"
  type        = number
  default     = 256
}

# O índice ANN do quadro-chave fica desligado até a busca por imagem (ADR 0006): cada
# índice cobra réplicas por hora. O campo do vetor continua na coleção; ligar só cria o
# índice (make criar-colecao-da-busca, depois do apply).
variable "indice_do_quadro_ligado" {
  type    = bool
  default = false
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

provider "google" {
  project        = var.projeto
  region         = var.regiao
  default_labels = { app = "mam" }
}

resource "google_project_service" "apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "eventarc.googleapis.com",
    "firestore.googleapis.com",
    "identitytoolkit.googleapis.com",
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
      origin          = google_cloud_run_v2_service.web.urls
      method          = ["POST", "PUT"]
      response_header = ["Content-Type", "Content-Range", "x-goog-resumable", "x-upload-content-length", "Location", "Range"]
      max_age_seconds = 3600
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_service_account" "mam" {
  for_each     = toset(["web", "validacao", "transcricao", "ocr", "analise", "quadros", "indexacao", "referencias", "identificacao", "comparacao", "orquestracao", "build"])
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
  papeis_no_projeto = {
    # `workflows.invoker` é só iniciar execuções (o reprocessar do #147), e o projeto tem
    # um único workflow.
    web         = ["roles/datastore.user", "roles/vectorsearch.dataObjectWriter", "roles/aiplatform.user", "roles/workflows.invoker"]
    validacao   = ["roles/datastore.user"]
    transcricao = ["roles/datastore.user"]
    ocr         = ["roles/datastore.user"]
    analise     = ["roles/datastore.user", "roles/aiplatform.user"]
    quadros     = ["roles/datastore.user"]
    # Grava o estado da indexação no Job e escreve na coleção da busca (gravar, apagar,
    # consultar e buscar; conferido no #122). A conta `web` tem o mesmo papel, porque
    # reindexa a cada Correção e busca. Nenhuma das duas cria ou apaga coleção. O
    # embedding automático da coleção roda com a credencial de quem grava ou busca, e não
    # com a do Agent Retrieval: as duas precisam chamar a Vertex (aiplatform.user).
    indexacao   = ["roles/datastore.user", "roles/vectorsearch.dataObjectWriter", "roles/aiplatform.user"]
    referencias = ["roles/datastore.user", "roles/aiplatform.user"]
    # Leem o Job, o catálogo e a Decupagem no Firestore e chamam o Gemini; a comparação
    # também grava as sugestões de perfil.
    identificacao = ["roles/datastore.user", "roles/aiplatform.user"]
    comparacao    = ["roles/datastore.user", "roles/aiplatform.user"]
    orquestracao  = ["roles/datastore.user", "roles/eventarc.eventReceiver", "roles/workflows.invoker", "roles/run.viewer"]
    # O Cloud Build com conta própria só grava log no Cloud Logging.
    build = ["roles/logging.logWriter"]
  }
  papeis_nos_buckets = {
    # A API assina as URLs de envio para a quarentena, apaga dela o upload cancelado e lê o proxy de reprodução e a decupagem.
    web = { quarentena = "roles/storage.objectUser", aceitos = "roles/storage.objectViewer", decupagens = "roles/storage.objectViewer" }
    # Lê e apaga o original da quarentena; grava a cópia limpa e o proxy de reprodução.
    validacao = { quarentena = "roles/storage.objectUser", aceitos = "roles/storage.objectCreator" }
    # Lê o áudio que a validação separou e grava a transcrição ao lado do proxy.
    transcricao = { aceitos = "roles/storage.objectUser" }
    # Lê o proxy e grava a leitura da tela ao lado dele.
    ocr = { aceitos = "roles/storage.objectUser" }
    # O Gemini lê o proxy de reprodução; o progresso das janelas é regravado ao lado dele
    # (objectUser, porque cada janela sobrescreve o próprio objeto); a decupagem vai para o
    # bucket dela.
    analise = { aceitos = "roles/storage.objectUser", decupagens = "roles/storage.objectCreator" }
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
  }
}

resource "google_project_iam_member" "mam" {
  for_each = { for p in flatten([
    for sa, papeis in local.papeis_no_projeto : [for papel in papeis : { sa = sa, papel = papel }]
  ]) : "${p.sa}:${p.papel}" => p }
  project = var.projeto
  role    = each.value.papel
  member  = google_service_account.mam[each.value.sa].member
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

# A mam-terraform nasce no wizard, fora do Terraform; aqui só ganha quem a impersona.
resource "google_service_account_iam_member" "github_impersona_terraform" {
  service_account_id = "projects/${var.projeto}/serviceAccounts/mam-terraform@${var.projeto}.iam.gserviceaccount.com"
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${local.repositorio_github_id}"
}

resource "google_cloud_run_v2_service" "web" {
  name                = "mam-web"
  location            = var.regiao
  deletion_protection = false
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
        name  = "BUSCA_DISTANCIA_MAXIMA"
        value = tostring(var.busca_distancia_maxima)
      }
      env {
        name  = "BUSCA_PALAVRAS_MINIMAS"
        value = tostring(var.busca_palavras_minimas)
      }
      # Quem tem esses e-mails (verificados) é Administrador (api/papeis.py).
      env {
        name  = "ADMINS_EMERGENCIA"
        value = var.admins_emergencia
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
# Ainda fora do Workflows (parte 4 do #112).
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
# Ainda fora do Workflows (parte 4 do #112).
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

# Quarentena -> Eventarc -> Workflows -> Job de validação -> Job de transcrição -> Job de OCR -> Job de análise -> Job de quadros -> Job de indexação.
locals {
  workflow_validacao = "mam-validacao"
}

resource "google_workflows_workflow" "validacao" {
  name            = local.workflow_validacao
  region          = var.regiao
  service_account = google_service_account.mam["orquestracao"].id
  source_contents = templatefile("${path.module}/validacao.workflow.yaml", {
    projeto            = var.projeto
    regiao             = var.regiao
    job_de_validacao   = google_cloud_run_v2_job.validacao.name
    job_de_transcricao = google_cloud_run_v2_job.transcricao.name
    job_de_ocr         = google_cloud_run_v2_job.ocr.name
    job_de_analise     = google_cloud_run_v2_job.analise.name
    job_de_quadros     = google_cloud_run_v2_job.quadros.name
    job_de_indexacao   = google_cloud_run_v2_job.indexacao.name
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

# URL pública: sem balanceador na E0, e a API exige o token do Identity Platform.
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
  }
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

# Chave web do login, que vai no build do front. O provider a marca como
# sensível, mas ela é pública por natureza: o cadastro bloqueado acima é o que protege.
output "identity_api_key" {
  value     = google_identity_platform_config.mam.client[0].api_key
  sensitive = true
}

output "url" {
  value = google_cloud_run_v2_service.web.uri
}

# Para as ferramentas locais: o deploy-dev envia as imagens a este repositório, e o
# make gravar-cassetes sobe o clipe sintético no bucket de clipes-ouro.
output "repositorio" {
  value = "${var.regiao}-docker.pkg.dev/${var.projeto}/${google_artifact_registry_repository.mam.repository_id}"
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
