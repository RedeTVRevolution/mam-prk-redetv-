#!/usr/bin/env bash
# `make criar-contas`: cria as contas locais do dev (#11) e manda a cada pessoa o
# link para definir a senha. Ninguém escolhe nem vê senha aqui: a conta nasce com
# uma aleatória, descartada. Rodar de novo só reenvia o link de quem já tem conta.
# Os e-mails vêm do .env: ADMINS_EMERGENCIA e USUARIOS, separados por vírgula.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

set -a
# shellcheck disable=SC1091
. ./.env
set +a
: "${GCP_PROJECT_ID:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${GOOGLE_IMPERSONATE_SERVICE_ACCOUNT:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${ADMINS_EMERGENCIA:?ponha no .env os e-mails dos 2 administradores de emergência, separados por vírgula}"
: "${USUARIOS:?ponha no .env os e-mails dos usuários (Bruno), separados por vírgula}"
export CLOUDSDK_ACTIVE_CONFIG_NAME=mam-dev

TOKEN=$(gcloud auth print-access-token --impersonate-service-account "$GOOGLE_IMPERSONATE_SERVICE_ACCOUNT")
CONTAS="https://identitytoolkit.googleapis.com/v1/projects/$GCP_PROJECT_ID/accounts"

# chamar SUFIXO JSON: POST na API de contas do Identity Platform, com o JSON pela
# entrada padrão (a senha descartável não aparece no `ps`). Falha se não vier 2xx.
chamar() {
  curl -sS --fail-with-body -X POST "$CONTAS$1" \
    -H "Authorization: Bearer $TOKEN" \
    -H "x-goog-user-project: $GCP_PROJECT_ID" \
    -H "Content-Type: application/json" \
    -H "X-Firebase-Locale: pt-BR" \
    --data @- <<<"$2"
}

for email in ${ADMINS_EMERGENCIA//,/ } ${USUARIOS//,/ }; do
  # E-mail já verificado: quem define a senha pelo link prova que é dono dele, e o
  # cadastro do MFA exige e-mail verificado.
  if resposta=$(chamar "" "{\"email\":\"$email\",\"emailVerified\":true,\"password\":\"$(openssl rand -base64 32)Aa1!\"}"); then
    echo "Conta criada: $email"
  elif grep -q EMAIL_EXISTS <<<"$resposta"; then
    echo "Conta já existia: $email"
  else
    echo "Falha ao criar $email: $resposta" >&2
    exit 1
  fi
  chamar ":sendOobCode" "{\"requestType\":\"PASSWORD_RESET\",\"email\":\"$email\"}" >/dev/null
  echo "  link para definir a senha enviado"
done
