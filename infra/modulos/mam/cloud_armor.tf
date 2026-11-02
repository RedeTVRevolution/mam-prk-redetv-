# Cloud Armor na frente do serviço de back-end do balanceador (#295). Só existe com
# `dominio` preenchido (local.balanceador, em balanceador.tf). As variáveis ficam no main.tf.
#
# O Cloud Armor para na primeira regra que casa, e o `throttle` deixa passar quem está
# dentro do limite. Por isso, com a lista de IPs preenchida, o limite casa só com os IPs
# da RedeTV: quem está fora não casa com nada e cai na regra padrão, que barra.

locals {
  # A ordem da lista é a das prioridades (100, 101...): regra nova entra no fim.
  regras_waf = [
    "sqli-v33-stable",
    "xss-v33-stable",
    "lfi-v33-stable",
    "rce-v33-stable",
    "scannerdetection-v33-stable",
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
      preview  = !var.waf_ativo
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
    action   = "throttle"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = local.restringe_ip ? var.ips_da_redetv : ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = var.limite_de_requisicoes_por_ip
        interval_sec = 60
      }
    }
    description = local.restringe_ip ? "Limite por IP, só para os IPs da RedeTV" : "Limite por IP"
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
