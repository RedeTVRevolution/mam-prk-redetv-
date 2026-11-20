# `janelas_em_paralelo` só existe na raiz da prod (a dev não a declara): 0 e 1,5 são recusados
# e 1 é aceito (#760). Roda com:
#   terraform -chdir=infra/ambientes/prod init -backend=false -input=false
#   terraform -chdir=infra/ambientes/prod test
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

run "zero_e_recusado" {
  command = plan
  variables {
    janelas_em_paralelo = 0
  }
  expect_failures = [var.janelas_em_paralelo]
}

run "um_e_meio_e_recusado" {
  command = plan
  variables {
    janelas_em_paralelo = 1.5
  }
  expect_failures = [var.janelas_em_paralelo]
}

run "um_e_aceito" {
  command = plan
  variables {
    janelas_em_paralelo = 1
  }
}
