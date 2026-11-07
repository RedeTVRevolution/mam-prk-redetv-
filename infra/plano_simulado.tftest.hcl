mock_provider "google" {}

# O import do Identity Platform não roda com provider simulado.
override_resource {
  target = module.mam.google_identity_platform_config.mam
}

variables {
  projeto                = "projeto-x"
  regiao                 = "southamerica-east1"
  admins_emergencia      = "a@x.com"
  imagem                 = "img@sha256:a"
  imagem_validacao       = "img@sha256:a"
  imagem_transcricao     = "img@sha256:a"
  imagem_ocr             = "img@sha256:a"
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
}
