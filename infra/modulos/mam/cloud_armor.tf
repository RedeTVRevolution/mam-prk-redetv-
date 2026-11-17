# Cloud Armor na frente do serviço de back-end do balanceador (#295). Só existe com
# `dominio` preenchido (local.balanceador, em balanceador.tf). As variáveis ficam no main.tf.
#
# O Cloud Armor para na primeira regra que casa. Com a lista de IPs preenchida (#366), a
# regra 200 libera só os IPs da RedeTV, sem limite por IP (a emissora inteira sai por
# poucos IPs de NAT ou VPN), e quem está fora cai na regra padrão, que barra. Com a lista
# vazia, a regra 200 é o limite por IP para todos.

locals {
  # A ordem da lista é a das prioridades (100, 101...): regra nova entra no fim.
  regras_waf = concat([
    "sqli-v33-stable",
    "xss-v33-stable",
    "lfi-v33-stable",
    "rce-v33-stable",
    "scannerdetection-v33-stable",
  ], local.regras_waf_em_observacao)
  # Só registram no log, mesmo com `waf_ativo`, até os logs mostrarem que não barram
  # ninguém da RedeTV; aí passam para o fim da lista de cima e começam a bloquear.
  regras_waf_em_observacao = [
    "rfi-v33-stable",
    "protocolattack-v33-stable",
    "sessionfixation-v33-stable",
    "cve-canary",
  ]
  restringe_ip = length(var.ips_da_redetv) > 0
}

resource "google_compute_security_policy" "web" {
  count      = local.balanceador ? 1 : 0
  name       = "mam-web"
  depends_on = [google_project_service.apis]

  dynamic "rule" {
    for_each = { for i, regra in local.regras_waf : regra => 100 + i }
    content {
      priority = rule.value
      action   = "deny(403)"
      preview  = !var.waf_ativo || contains(local.regras_waf_em_observacao, rule.key)
      match {
        expr {
          expression = "evaluatePreconfiguredWaf('${rule.key}', {'sensitivity': 1})"
        }
      }
      description = "WAF ${rule.key}"
    }
  }

  rule {
    priority = 200
    action   = local.restringe_ip ? "allow" : "throttle"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = local.restringe_ip ? var.ips_da_redetv : ["*"]
      }
    }
    dynamic "rate_limit_options" {
      for_each = local.restringe_ip ? [] : [1]
      content {
        conform_action = "allow"
        exceed_action  = "deny(429)"
        enforce_on_key = "IP"
        rate_limit_threshold {
          count        = var.limite_de_requisicoes_por_ip
          interval_sec = 60
        }
      }
    }
    description = local.restringe_ip ? "Só os IPs da RedeTV" : "Limite por IP"
  }

  # Regra padrão: com a lista preenchida, quem não está nela é barrado.
  rule {
    priority = 2147483647
    action   = local.restringe_ip ? "deny(403)" : "allow"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Regra padrão"
  }
}
