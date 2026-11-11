mock_provider "google" {}

override_resource {
  target = google_identity_platform_config.mam
}

variables {
  projeto                = "projeto-x"
  regiao                 = "us-east4"
  admins_emergencia      = "a@x.com"
  imagem                 = "img@sha256:a"
  imagem_validacao       = "img@sha256:a"
  imagem_transcricao_gpu = "img@sha256:a"
  imagem_ocr_gpu         = "img@sha256:a"
  imagem_objetos         = "img@sha256:a"
}

run "plano" {
  command = plan

  module {
    source = "./modulos/mam"
  }

  # Os 3 tópicos só persistem mensagens na região do projeto (#564).
  assert {
    condition = alltrue([
      for t in [
        google_pubsub_topic.eventos_do_job,
        google_pubsub_topic.eventos_mortos,
        google_pubsub_topic.eventos_de_uso,
      ] : length(t.message_storage_policy) == 1 && one(t.message_storage_policy[0].allowed_persistence_regions) == "us-east4"
    ])
    error_message = "Os 3 tópicos do Pub/Sub devem ter message_storage_policy com a região."
  }

  # Limpeza das imagens: GPU 7 dias, comum 14; as regras KEEP são as mesmas nos dois.
  assert {
    condition     = one([for p in google_artifact_registry_repository.mam_gpu.cleanup_policies : p.condition[0].older_than if p.action == "DELETE"]) == "604800s"
    error_message = "O repositório com GPU apaga o resto com mais de 7 dias."
  }
  assert {
    condition     = one([for p in google_artifact_registry_repository.mam.cleanup_policies : p.condition[0].older_than if p.action == "DELETE"]) == "1209600s"
    error_message = "O repositório comum apaga o resto com mais de 14 dias."
  }
  assert {
    condition = (
      { for p in google_artifact_registry_repository.mam.cleanup_policies : p.id => p if p.action == "KEEP" }
      == { for p in google_artifact_registry_repository.mam_gpu.cleanup_policies : p.id => p if p.action == "KEEP" }
      && length([for p in google_artifact_registry_repository.mam.cleanup_policies : p if p.action == "KEEP"]) == 3
    )
    error_message = "As 3 regras KEEP devem ser iguais nos dois repositórios."
  }
  assert {
    condition     = output.limpeza_de_imagens.idade_minima_s == { mam = 1209600, mam-gpu = 604800 }
    error_message = "O output da limpeza dá a idade de cada repositório."
  }

  # Etapa 1 da remoção da tabela antiga de momentos: sem proteção e ainda presente.
  assert {
    condition     = google_bigquery_table.momentos.deletion_protection == false
    error_message = "A tabela antiga de momentos fica sem a proteção, ainda presente."
  }
}
