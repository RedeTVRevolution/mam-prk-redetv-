mock_provider "google" {}

# O import do Identity Platform não roda com provider simulado.
override_resource {
  target = module.mam.google_identity_platform_config.mam
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

  # O dev roda com o índice ANN da descrição (ADR 0006).
  assert {
    condition     = output.busca_indices_ligados == true
    error_message = "O dev deve rodar com indices_da_busca_ligados = true."
  }

  # Tudo em us-east4 (ADR 0019): uma região só, e os nomes novos levam a região no nome
  # (os de São Paulo seguem existindo até o fim da cópia).
  assert {
    condition     = output.regiao == "us-east4" && output.bigquery_regiao == "us-east4" && output.workflow_regiao == "us-east4" && output.regiao_gpu == "us-east4" && output.busca_regiao == "us-east4"
    error_message = "Toda região do dev deve ser us-east4."
  }
  assert {
    condition     = output.buckets["quarentena"] == "projeto-x-useast4-quarentena" && output.bucket_fontes == "projeto-x-useast4-fontes"
    error_message = "Os buckets novos levam a região no nome."
  }
  assert {
    condition     = output.datasets_bigquery == { decupagens = "mam_decupagens_useast4", faturamento = "faturamento_useast4" }
    error_message = "Os datasets novos levam a região no nome."
  }
  assert {
    condition     = output.banco_firestore == "mam" && output.banco_de_seguranca == "mam-seguranca-useast4"
    error_message = "Os bancos do Firestore são nomeados."
  }
}
