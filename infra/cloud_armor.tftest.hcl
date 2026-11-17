# As regras do Cloud Armor com e sem a lista de IPs da RedeTV (#366), no plano simulado.
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
  dominio                = "exemplo.com"
  waf_ativo              = true
}

run "sem_a_lista_limite_por_ip_para_todos" {
  command = plan
  module {
    source = "./modulos/mam"
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.web[0].rule : r.action == "throttle" && r.match[0].config[0].src_ip_ranges == toset(["*"]) && r.rate_limit_options[0].rate_limit_threshold[0].count == 600
      if r.priority == 200
    ])
    error_message = "Sem a lista, a regra 200 é o limite de 600 por minuto para qualquer IP."
  }
  assert {
    condition     = one([for r in google_compute_security_policy.web[0].rule : r.action if r.priority == 2147483647]) == "allow"
    error_message = "Sem a lista, a regra padrão deixa passar."
  }
  # Com o WAF ligado, todas bloqueiam.
  assert {
    condition = alltrue([
      for r in google_compute_security_policy.web[0].rule : !r.preview
      if r.priority < 200
    ])
    error_message = "Com o WAF ligado, as nove regras bloqueiam."
  }
  assert {
    condition     = length([for r in google_compute_security_policy.web[0].rule : r if r.priority < 200]) == 9
    error_message = "São nove regras do WAF."
  }
}

run "com_a_lista_so_a_redetv_e_sem_limite" {
  command = plan
  module {
    source = "./modulos/mam"
  }
  variables {
    ips_da_redetv = ["200.1.2.0/24", "200.3.4.5"]
  }

  assert {
    condition = one([
      for r in google_compute_security_policy.web[0].rule : r.action == "allow" && r.match[0].config[0].src_ip_ranges == toset(["200.1.2.0/24", "200.3.4.5"]) && length(r.rate_limit_options) == 0
      if r.priority == 200
    ])
    error_message = "Com a lista, a regra 200 libera só os IPs da RedeTV, sem limite por IP."
  }
  assert {
    condition     = one([for r in google_compute_security_policy.web[0].rule : r.action if r.priority == 2147483647]) == "deny(403)"
    error_message = "Com a lista, quem está fora cai na regra padrão e leva 403."
  }
  # O WAF vem antes da regra 200 e vale para todos, só barrando.
  assert {
    condition     = alltrue([for r in google_compute_security_policy.web[0].rule : r.action == "deny(403)" if r.priority < 200])
    error_message = "As regras antes da 200 só podem barrar."
  }
}
