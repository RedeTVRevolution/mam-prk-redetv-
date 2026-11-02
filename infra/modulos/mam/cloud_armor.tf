# Cloud Armor na frente do serviço de back-end do balanceador (#295). Só existe com
# `dominio` preenchido (local.balanceador, em balanceador.tf).

variable "waf_ativo" {
  description = "Falso: as regras WAF só registram no log o que bloqueariam (prévia). Verdadeiro: bloqueiam de verdade (403). Ligue depois de olhar os logs da prévia"
  type        = bool
  default     = false
}

variable "limite_de_requisicoes_por_ip" {
  description = "Requisições por minuto por IP; acima disso, 429"
  type        = number
  default     = 600
}

variable "ips_da_redetv" {
  description = "IPs ou CIDRs da RedeTV. Vazio: sem restrição de IP. Preenchido: só eles passam, em todas as rotas, as /v1 dos sistemas inclusive"
  type        = list(string)
  default     = []
}

locals {
  regras_waf = {
    sqli             = "sqli-v33-stable"
    xss              = "xss-v33-stable"
    lfi              = "lfi-v33-stable"
    rce              = "rce-v33-stable"
    scannerdetection = "scannerdetection-v33-stable"
  }
}

resource "google_compute_security_policy" "web" {
  count      = local.balanceador ? 1 : 0
  name       = "mam-web"
  depends_on = [google_project_service.apis]

  dynamic "rule" {
    for_each = { for i, k in keys(local.regras_waf) : k => 100 + i }
    content {
      priority = rule.value
      action   = "deny(403)"
      preview  = !var.waf_ativo
      match {
        expr {
          expression = "evaluatePreconfiguredWaf('${local.regras_waf[rule.key]}', {'sensitivity': 1})"
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
        src_ip_ranges = ["*"]
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
    description = "Limite de requisições por IP"
  }

  # Só com a lista preenchida: deixa passar os IPs da RedeTV (depois do WAF e do limite).
  dynamic "rule" {
    for_each = length(var.ips_da_redetv) > 0 ? [1] : []
    content {
      priority = 1000
      action   = "allow"
      match {
        versioned_expr = "SRC_IPS_V1"
        config {
          src_ip_ranges = var.ips_da_redetv
        }
      }
      description = "IPs da RedeTV"
    }
  }

  # Regra padrão: com a lista preenchida, quem não está nela é barrado.
  rule {
    priority = 2147483647
    action   = length(var.ips_da_redetv) > 0 ? "deny(403)" : "allow"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Regra padrão"
  }
}
