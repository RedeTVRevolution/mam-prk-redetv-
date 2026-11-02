# Balanceador HTTPS externo global na frente do serviço web (#294). Só nasce com `dominio`
# preenchido: vazio, nada daqui é criado e o endereço continua o run.app. A política do Cloud Armor
# (cloud_armor.tf, #295) vai neste serviço de back-end.
#
# Na `main.tf` ficam o `ingress` do Cloud Run, o CORS da quarentena e os domínios do login,
# que mudam com o balanceador. Aqui ficam só os recursos novos (sem `moved`: nunca
# existiram fora do módulo).

locals {
  balanceador = var.dominio != ""
}

resource "google_compute_global_address" "balanceador" {
  count      = local.balanceador ? 1 : 0
  name       = "mam-balanceador"
  depends_on = [google_project_service.apis]
}

# O NEG serverless aponta para o serviço web, que serve o front e a API.
resource "google_compute_region_network_endpoint_group" "web" {
  count                 = local.balanceador ? 1 : 0
  name                  = "mam-web"
  region                = var.regiao
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_v2_service.web.name
  }
}

resource "google_compute_backend_service" "web" {
  count                 = local.balanceador ? 1 : 0
  name                  = "mam-web"
  protocol              = "HTTPS"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  security_policy       = google_compute_security_policy.web[0].id
  backend {
    group = google_compute_region_network_endpoint_group.web[0].id
  }
  # Os logs do balanceador entram na auditoria (docs/Plano_MAM.md, "Auditoria").
  log_config {
    enable      = true
    sample_rate = 1.0
  }
}

resource "google_compute_url_map" "web" {
  count           = local.balanceador ? 1 : 0
  name            = "mam-web"
  default_service = google_compute_backend_service.web[0].id
}

# O nome leva um sufixo do domínio: se o domínio mudar, o certificado novo nasce (outro nome)
# antes de o antigo sair.
resource "google_compute_managed_ssl_certificate" "web" {
  count = local.balanceador ? 1 : 0
  name  = "mam-web-${substr(md5(var.dominio), 0, 8)}"
  managed {
    domains = [var.dominio]
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_target_https_proxy" "web" {
  count            = local.balanceador ? 1 : 0
  name             = "mam-web"
  url_map          = google_compute_url_map.web[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.web[0].id]
}

resource "google_compute_global_forwarding_rule" "https" {
  count                 = local.balanceador ? 1 : 0
  name                  = "mam-web-https"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.balanceador[0].id
  port_range            = "443"
  target                = google_compute_target_https_proxy.web[0].id
}

# Quem entra por http:// vai para https:// no mesmo endereço.
resource "google_compute_url_map" "redireciona_para_https" {
  count = local.balanceador ? 1 : 0
  name  = "mam-web-http"
  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "redireciona_para_https" {
  count   = local.balanceador ? 1 : 0
  name    = "mam-web-http"
  url_map = google_compute_url_map.redireciona_para_https[0].id
}

resource "google_compute_global_forwarding_rule" "http" {
  count                 = local.balanceador ? 1 : 0
  name                  = "mam-web-http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.balanceador[0].id
  port_range            = "80"
  target                = google_compute_target_http_proxy.redireciona_para_https[0].id
}

# O registro A do domínio aponta para este endereço. Nulo sem balanceador.
output "ip_do_balanceador" {
  value = local.balanceador ? google_compute_global_address.balanceador[0].address : null
}

# O deploy confere o estado dele antes de testar o /v1/health pelo domínio. Nulo sem balanceador.
output "certificado_do_balanceador" {
  value = local.balanceador ? google_compute_managed_ssl_certificate.web[0].name : null
}
