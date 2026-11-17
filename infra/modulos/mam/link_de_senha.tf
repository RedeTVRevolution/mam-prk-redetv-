# O link do e-mail de senha (conta nova ou "Reenviar link") abre a página `/redefinir-senha` do
# próprio MAM, que volta sozinha ao login; sem isso, cai na página padrão do Firebase, que não volta.
# O provider também não tem este campo (notification.sendEmail.callbackUri): vai pela API REST.
# Ordem: a web com a rota nova tem de estar no ar antes de este endereço mudar, senão os links
# quebram; o depends_on no serviço web garante isso no mesmo apply.
locals {
  url_da_acao_de_senha = jsonencode({
    notification = { sendEmail = { callbackUri = "${local.url_do_app}/redefinir-senha" } }
  })
}

resource "terraform_data" "url_da_acao_de_senha" {
  triggers_replace = [local.url_da_acao_de_senha]
  provisioner "local-exec" {
    command = <<-EOT
      curl -sSf -o /dev/null -X PATCH \
        "https://identitytoolkit.googleapis.com/admin/v2/projects/${var.projeto}/config?updateMask=notification.sendEmail.callbackUri" \
        -H "Authorization: Bearer $(gcloud auth print-access-token --impersonate-service-account "$GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")" \
        -H "x-goog-user-project: ${var.projeto}" \
        -H "Content-Type: application/json" \
        -d '${local.url_da_acao_de_senha}'
    EOT
  }
  depends_on = [google_identity_platform_config.mam, google_cloud_run_v2_service.web]
}
