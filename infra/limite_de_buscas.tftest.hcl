# Limite de buscas por minuto do mam-web, configurável na raiz (#577).
mock_provider "google" {}

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

run "padrao_e_30" {
  command = plan

  assert {
    condition     = output.busca_consultas_por_minuto == "30"
    error_message = "Sem a variável, o mam-web recebe 30."
  }
}

run "valor_configurado_chega_ao_mam_web" {
  command = plan

  variables {
    busca_consultas_por_minuto = 600
  }

  assert {
    condition     = output.busca_consultas_por_minuto == "600"
    error_message = "O mam-web recebe o valor configurado na raiz."
  }
}

run "chave_do_cabecalho_de_teste_padrao_e_desligada" {
  command = plan

  assert {
    condition     = output.busca_aceita_teste_de_carga == "false"
    error_message = "Sem a variável, o mam-web recebe a chave desligada."
  }
}

run "chave_do_cabecalho_de_teste_configurada_chega_ao_mam_web" {
  command = plan

  variables {
    busca_aceita_teste_de_carga = true
  }

  assert {
    condition     = output.busca_aceita_teste_de_carga == "true"
    error_message = "O mam-web recebe o valor configurado na raiz."
  }
}

run "recusa_zero" {
  command = plan

  variables {
    busca_consultas_por_minuto = 0
  }

  expect_failures = [var.busca_consultas_por_minuto]
}

run "recusa_fracao" {
  command = plan

  variables {
    busca_consultas_por_minuto = 1.5
  }

  expect_failures = [var.busca_consultas_por_minuto]
}
