#!/usr/bin/env bash
# `make deploy-dev`: põe a aplicação no ar no dev (#8). Tudo roda como a conta
# mam-terraform, por impersonação e sem chave em arquivo (ADR 0002). Os valores
# vêm do .env que o scripts/wizard-gcp-dev.sh escreveu, e ADMINS_EMERGENCIA (#11)
# se põe à mão.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

set -a
# shellcheck disable=SC1091
. ./.env
set +a
: "${GCP_PROJECT_ID:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${GCP_REGION:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${GOOGLE_IMPERSONATE_SERVICE_ACCOUNT:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${ADMINS_EMERGENCIA:?ponha no .env os e-mails dos administradores de emergência, separados por vírgula}"
# A config gcloud do MAM, criada pelo wizard, sem mexer na config ativa.
export CLOUDSDK_ACTIVE_CONFIG_NAME=mam-dev
export TF_VAR_projeto="$GCP_PROJECT_ID" TF_VAR_regiao="$GCP_REGION" TF_VAR_admins_emergencia="$ADMINS_EMERGENCIA"

gc() { gcloud --project "$GCP_PROJECT_ID" --impersonate-service-account "$GOOGLE_IMPERSONATE_SERVICE_ACCOUNT" "$@"; }
tf() { terraform -chdir=infra "$@"; }

# O estado precisa existir antes do `terraform init`. Bucket privado, sem acesso
# público: só papéis do projeto o alcançam, e no dev são o Owner e a mam-terraform.
ESTADO="$GCP_PROJECT_ID-tfstate"
if ! gc storage buckets describe "gs://$ESTADO" >/dev/null 2>&1; then
  gc storage buckets create "gs://$ESTADO" --location "$GCP_REGION" \
    --uniform-bucket-level-access --public-access-prevention
  gc storage buckets update "gs://$ESTADO" --versioning --update-labels app=mam
fi
tf init -input=false -backend-config="bucket=$ESTADO"

# A imagem precisa do repositório e da chave web do Identity Platform, e o
# serviço precisa da imagem. Este apply só cria os dois, então a imagem ainda não importa.
tf apply -input=false -target=google_artifact_registry_repository.mam \
  -target=google_identity_platform_config.mam -var imagem=pendente -var imagem_validacao=pendente
REGISTRO="$GCP_REGION-docker.pkg.dev"
REPO="$REGISTRO/$GCP_PROJECT_ID/mam/web"
TAG="$REPO:$(git rev-parse --short HEAD)"
gc auth print-access-token | docker login -u oauth2accesstoken --password-stdin "https://$REGISTRO"
docker build --platform linux/amd64 -t "$TAG" \
  --build-arg VITE_IDENTITY_API_KEY="$(tf output -raw identity_api_key)" .
docker push "$TAG"
# Pelo digest, para que um rebuild com o mesmo commit também gere revisão nova.
IMAGEM=$(docker inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$TAG" | grep -m1 "^$REPO@")
# A imagem do Job de validação (#38), também pelo digest.
REPO_VALIDACAO="$REGISTRO/$GCP_PROJECT_ID/mam/validacao"
TAG_VALIDACAO="$REPO_VALIDACAO:$(git rev-parse --short HEAD)"
docker build --platform linux/amd64 --target validacao -t "$TAG_VALIDACAO" .
docker push "$TAG_VALIDACAO"
IMAGEM_VALIDACAO=$(docker inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$TAG_VALIDACAO" | grep -m1 "^$REPO_VALIDACAO@")
tf apply -input=false -var "imagem=$IMAGEM" -var "imagem_validacao=$IMAGEM_VALIDACAO"

URL=$(tf output -raw url)
curl -sSf "$URL/v1/health" >/dev/null
echo "No ar: $URL (/v1/health respondeu 200)"
