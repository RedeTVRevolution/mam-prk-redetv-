# O PATCH da URL de ação do e-mail de senha (notification.sendEmail.callbackUri) é recusado
# pelo Identity Platform com 400 EMAIL_TEMPLATE_UPDATE_NOT_ALLOWED, e essa URL valeria para todos
# os e-mails do projeto. O link continua na página padrão do Google, com o botão "Continuar" de
# volta ao MAM (continueUrl, api/nuvem.py). O recurso que fazia o PATCH sai só do estado: o
# aplicar-sem-destruir.sh recusa delete, e apagar o recurso não desfaria nada na nuvem.
removed {
  from = terraform_data.url_da_acao_de_senha
  lifecycle {
    destroy = false
  }
}

# O código do link (`oobCode`) vale até ser usado: se uma URL com ele chegar aos logs, quem os lesse
# poderia definir a senha da conta. O balanceador e o Cloud Run gravam a URL no httpRequest e
# o uvicorn, no texto do acesso; essas linhas não entram no bucket de logs.
resource "google_logging_project_exclusion" "codigo_do_link_de_senha" {
  name        = "codigo-do-link-de-senha"
  description = "Descarta os logs com o código do link de senha do e-mail (oobCode)."
  filter      = "httpRequest.requestUrl:\"oobCode=\" OR httpRequest.referer:\"oobCode=\" OR textPayload:\"oobCode=\""
}
