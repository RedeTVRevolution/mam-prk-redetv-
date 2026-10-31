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
    "workflows.googleapis.com",
    # Ligadas antes pelo wizard; aqui para que o Terraform as declare.
    "aiplatform.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
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

# O único lugar que monta os nomes dos buckets. O código os recebe por variável
# de ambiente (BUCKET_*), e o `make verificar` recusa sufixo escrito em api/ ou
# web/src/ (scripts/checar-nomes-da-nuvem.sh lê a lista desta linha).
locals {
  sufixos_dos_buckets = ["quarentena", "aceitos", "decupagens", "clipes-ouro"]
  buckets             = { for s in local.sufixos_dos_buckets : s => "${var.projeto}-${s}" }
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
  for_each     = toset(["web", "validacao", "transcricao", "analise", "orquestracao", "build"])
  account_id   = "mam-${each.key}"
  display_name = "MAM ${each.key}"
}

# Papéis de cada componente. A orquestração grava a falha da validação no
# Firestore, recebe o evento do Eventarc e invoca o Workflows (o provider não tem
# papel no próprio Workflows); o papel de rodar o Job fica mais abaixo, no próprio
# Job (ADR 0002), e o de chamar o serviço de análise, no próprio serviço. Quem lê o
# proxy por gs:// na Vertex é a conta que chama (mam-analise, com objectViewer em
# aceitos), segundo a doc do generateContent; o agente de serviço da Vertex não
# precisa de papel no bucket. O run.viewer da orquestração fica no projeto porque o
# conector do Workflows acompanha a execução do Job pela operação, que é do projeto e
# não do Job; sem ele, o passo `valida` falharia depois de o Job rodar e marcaria um
# vídeo bom como arquivo_corrompido.
locals {
  papeis_no_projeto = {
    web          = ["roles/datastore.user"]
    validacao    = ["roles/datastore.user"]
    transcricao  = ["roles/datastore.user"]
    analise      = ["roles/datastore.user", "roles/aiplatform.user"]
    orquestracao = ["roles/datastore.user", "roles/eventarc.eventReceiver", "roles/workflows.invoker", "roles/run.viewer"]
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
    # O Gemini lê o proxy de reprodução; a decupagem vai para o bucket dela.
    analise = { aceitos = "roles/storage.objectViewer", decupagens = "roles/storage.objectCreator" }
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
      # Quem tem esses e-mails (verificados) é Administrador (api/papeis.py).
      env {
        name  = "ADMINS_EMERGENCIA"
        value = var.admins_emergencia
      }
    }
  }
  depends_on = [google_project_service.apis]
}

# Rede só para o Job de validação: sem IP externo e sem Cloud NAT, o arquivo
# hostil não alcança a internet, só o Storage e o Firestore (pelo acesso privado do Google).
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
      timeout     = "1800s"
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
          # ponytail: teto de 4 GiB por arquivo (TAMANHO_MAXIMO_PADRAO_BYTES). A cópia
          # limpa tem o tamanho do original (até 4 GiB) e o proxy de 480p é bem menor
          # (dezenas de MiB). O volume em memória conta na memória do contêiner:
          # 4 GiB da cópia + 1 GiB do proxy e do ffmpeg, e 3 GiB de folga = 8 GiB.
          # 4 vCPU: o proxy do clipe2 caiu 26% de 2 para 4 threads, e 8 não ganharam nada.
          limits = {
            cpu    = "4"
            memory = "8Gi"
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
          size_limit = "5Gi"
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
      timeout         = "3600s"
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
          # O modelo large-v3-turbo em int8 cabe em poucos GiB; o áudio de até 10 min
          # em WAV mono de 16 kHz tem ~19 MiB.
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
          size_limit = "1Gi"
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

# A orquestração roda o Job com override de JOB_ID.
resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda" {
  name     = google_cloud_run_v2_job.validacao.name
  location = google_cloud_run_v2_job.validacao.location
  role     = "roles/run.developer"
  member   = google_service_account.mam["orquestracao"].member
}

# Serviço de análise (#39): a mesma imagem do web, com outro comando. Entrada só
# interna (sem allUsers): o Workflows o chama por OIDC, e a chamada de dentro do
# Google Cloud passa pelo ingress interno. O timeout acompanha o teto de 1800 s da
# chamada HTTP do Workflows.
resource "google_cloud_run_v2_service" "analise" {
  name                = "mam-analise"
  location            = var.regiao
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = false
  template {
    service_account                  = google_service_account.mam["analise"].email
    timeout                          = "1800s"
    max_instance_request_concurrency = 8
    scaling {
      max_instance_count = 5
    }
    containers {
      image   = var.imagem
      command = ["uvicorn"]
      args    = ["api.analise:app", "--host", "0.0.0.0", "--port", "8080"]
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
    }
  }
  depends_on = [google_project_service.apis, google_storage_bucket_iam_member.mam]
}

# A orquestração chama o serviço de análise.
resource "google_cloud_run_v2_service_iam_member" "orquestracao_chama_analise" {
  name     = google_cloud_run_v2_service.analise.name
  location = google_cloud_run_v2_service.analise.location
  role     = "roles/run.invoker"
  member   = google_service_account.mam["orquestracao"].member
}

# Quarentena -> Eventarc -> Workflows -> Job de validação -> Job de transcrição -> serviço de análise.
resource "google_workflows_workflow" "validacao" {
  name            = "mam-validacao"
  region          = var.regiao
  service_account = google_service_account.mam["orquestracao"].id
  source_contents = templatefile("${path.module}/validacao.workflow.yaml", {
    projeto            = var.projeto
    regiao             = var.regiao
    job_de_validacao   = google_cloud_run_v2_job.validacao.name
    job_de_transcricao = google_cloud_run_v2_job.transcricao.name
    url_da_analise     = google_cloud_run_v2_service.analise.uri
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
