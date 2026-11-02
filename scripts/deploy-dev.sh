#!/usr/bin/env bash
# `make deploy-dev`: põe a aplicação no ar no dev (#8). Tudo roda como a conta
# mam-terraform, por impersonação e sem chave em arquivo (ADR 0002). À mão, os
# valores vêm do .env que o scripts/wizard-gcp-dev.sh escreveu, e ADMINS_EMERGENCIA
# (#11) se põe à mão; no CD (#71), das variáveis do repositório no GitHub.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi
: "${GCP_PROJECT_ID:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${GCP_REGION:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${BUCKET_ESTADO_TF:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${GOOGLE_IMPERSONATE_SERVICE_ACCOUNT:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${ADMINS_EMERGENCIA:?ponha no .env os e-mails dos administradores de emergência, separados por vírgula}"
# A config gcloud do MAM, criada pelo wizard, sem mexer na config ativa. O CD usa a default.
export CLOUDSDK_ACTIVE_CONFIG_NAME="${CLOUDSDK_ACTIVE_CONFIG_NAME:-mam-dev}"
export TF_VAR_projeto="$GCP_PROJECT_ID" TF_VAR_regiao="$GCP_REGION" TF_VAR_admins_emergencia="$ADMINS_EMERGENCIA"

gc() { gcloud --project "$GCP_PROJECT_ID" --impersonate-service-account "$GOOGLE_IMPERSONATE_SERVICE_ACCOUNT" "$@"; }
tf() { terraform -chdir=infra "$@"; }

# O estado precisa existir antes do `terraform init`. Bucket privado, sem acesso
# público: só papéis do projeto o alcançam, e no dev são o Owner e a mam-terraform.
ESTADO="$BUCKET_ESTADO_TF"
if ! gc storage buckets describe "gs://$ESTADO" >/dev/null 2>&1; then
  gc storage buckets create "gs://$ESTADO" --location "$GCP_REGION" \
    --uniform-bucket-level-access --public-access-prevention
  gc storage buckets update "gs://$ESTADO" --versioning --update-labels app=mam
fi
tf init -input=false -backend-config="bucket=$ESTADO"

# A imagem precisa do repositório, da chave web do Identity Platform e do que o
# Cloud Build usa (#71), e o serviço precisa da imagem. Este apply só cria esses,
# então a imagem ainda não importa.
tf apply -input=false -target=google_artifact_registry_repository.mam \
  -target=google_identity_platform_config.mam -target=google_project_iam_member.mam \
  -target=google_storage_bucket_iam_member.build_le_fontes \
  -target=google_artifact_registry_repository_iam_member.build_envia \
  -target=google_artifact_registry_repository.mam_gpu \
  -target=google_artifact_registry_repository_iam_member.build_envia_gpu \
  -var imagem=pendente -var imagem_validacao=pendente -var imagem_transcricao=pendente -var imagem_ocr=pendente \
  -var imagem_transcricao_gpu=pendente -var imagem_ocr_gpu=pendente -var imagem_objetos=pendente
# O nome do repositório vem do Terraform, o único lugar que monta os nomes.
REPOSITORIO=$(tf output -raw repositorio)
COMMIT=$(git rev-parse --short HEAD)
WEB="$REPOSITORIO/web:$COMMIT"
# A imagem do Job de validação (#38).
VALIDACAO="$REPOSITORIO/validacao:$COMMIT"
# A imagem do Job de transcrição (#104), com o modelo do Whisper dentro.
TRANSCRICAO="$REPOSITORIO/transcricao:$COMMIT"
# A imagem do Job de OCR da tela (#106), com os modelos do PaddleOCR dentro.
OCR="$REPOSITORIO/ocr:$COMMIT"
# O cache das camadas (#211): uma tag por alvo no mesmo repositório, sobrescrita a cada montagem.
CACHE="$REPOSITORIO/cache"
# As imagens dos Jobs com GPU (E1, ADR 0007, #238) e o cache delas ficam no repositório da
# região da GPU: o envio da imagem não reenvia as camadas que o cache já pôs lá.
REPOSITORIO_GPU=$(tf output -raw repositorio_gpu)
TRANSCRICAO_GPU="$REPOSITORIO_GPU/transcricao-gpu:$COMMIT"
OCR_GPU="$REPOSITORIO_GPU/ocr-gpu:$COMMIT"
OBJETOS_GPU="$REPOSITORIO_GPU/objetos-gpu:$COMMIT"
CACHE_GPU="$REPOSITORIO_GPU/cache"
# Os Jobs com GPU e as imagens que têm hoje, lidas antes do apply, para o teste depois da
# publicação saber quais imagens mudaram e a que voltar. Vazias na primeira publicação: o
# Job ainda não está no estado do Terraform. Se ele está e o describe falha, a publicação
# para aqui, para não seguir sem a imagem a que voltar. Um Job com GPU a mais entra no
# teste com mais uma linha em JOBS_GPU, depois de ter o alvo de construção, o Job no
# Terraform e a imagem lida aqui e publicada pelo digest, como estes dois.
GPU_REGIAO=$(tf output -raw regiao_gpu 2>/dev/null || true)
imagem_do_job() {
  [[ -z $1 ]] && return 0
  gc run jobs describe "$1" --region "$GPU_REGIAO" --format='value(spec.template.spec.template.spec.containers[0].image)'
}
JOB_TRANSCRICAO_GPU_ANTES=$(tf output -raw job_de_transcricao_gpu 2>/dev/null || true)
JOB_OCR_GPU_ANTES=$(tf output -raw job_de_ocr_gpu 2>/dev/null || true)
JOB_OBJETOS_GPU_ANTES=$(tf output -raw job_de_objetos_gpu 2>/dev/null || true)
TRANSCRICAO_GPU_ANTES=$(imagem_do_job "$JOB_TRANSCRICAO_GPU_ANTES")
OCR_GPU_ANTES=$(imagem_do_job "$JOB_OCR_GPU_ANTES")
OBJETOS_GPU_ANTES=$(imagem_do_job "$JOB_OBJETOS_GPU_ANTES")
# O Cloud Build constrói, em paralelo e com cache, e envia as sete imagens (cloudbuild.yaml), como a mam-build.
gc builds submit . --region "$GCP_REGION" --suppress-logs \
  --service-account "$(tf output -raw conta_build)" \
  --gcs-source-staging-dir "gs://$(tf output -raw bucket_fontes)/fontes" \
  --substitutions "_WEB=$WEB,_VALIDACAO=$VALIDACAO,_TRANSCRICAO=$TRANSCRICAO,_OCR=$OCR,_CACHE=$CACHE,_TRANSCRICAO_GPU=$TRANSCRICAO_GPU,_OCR_GPU=$OCR_GPU,_OBJETOS_GPU=$OBJETOS_GPU,_CACHE_GPU=$CACHE_GPU,_VITE_IDENTITY_API_KEY=$(tf output -raw identity_api_key)"
# Pelo digest que o Cloud Build enviou, para que um rebuild com o mesmo commit
# também gere revisão nova. Daqui em diante nada é recompilado.
digest() { echo "${1%:*}@$(gc artifacts docker images describe "$1" --format='value(image_summary.digest)')"; }
IMAGEM=$(digest "$WEB")
IMAGEM_VALIDACAO=$(digest "$VALIDACAO")
IMAGEM_TRANSCRICAO=$(digest "$TRANSCRICAO")
IMAGEM_OCR=$(digest "$OCR")
IMAGEM_TRANSCRICAO_GPU=$(digest "$TRANSCRICAO_GPU")
IMAGEM_OCR_GPU=$(digest "$OCR_GPU")
IMAGEM_OBJETOS=$(digest "$OBJETOS_GPU")
tf apply -input=false -var "imagem=$IMAGEM" -var "imagem_validacao=$IMAGEM_VALIDACAO" \
  -var "imagem_transcricao=$IMAGEM_TRANSCRICAO" -var "imagem_ocr=$IMAGEM_OCR" \
  -var "imagem_transcricao_gpu=$IMAGEM_TRANSCRICAO_GPU" -var "imagem_ocr_gpu=$IMAGEM_OCR_GPU" \
  -var "imagem_objetos=$IMAGEM_OBJETOS"

# Teste dos Jobs com GPU (#238), só dos que mudaram: se não passar, o script volta os Jobs
# para a imagem anterior e esta publicação falha, e o Workflows não manda vídeo para uma
# imagem com GPU quebrada. Os Jobs em CPU não entram.
JOBS_GPU=(
  "$(tf output -raw job_de_transcricao_gpu),$TRANSCRICAO_GPU_ANTES,$IMAGEM_TRANSCRICAO_GPU"
  "$(tf output -raw job_de_ocr_gpu),$OCR_GPU_ANTES,$IMAGEM_OCR_GPU"
  "$(tf output -raw job_de_objetos_gpu),$OBJETOS_GPU_ANTES,$IMAGEM_OBJETOS"
)
GPU_REGIAO=$(tf output -raw regiao_gpu) GPU_ESPERA_TOTAL_S=$(tf output -raw gpu_espera_total_s) \
  GPU_ESPERA_S=$(tf output -raw gpu_espera_s) GPU_FATOR_DA_ESPERA=$(tf output -raw gpu_fator_da_espera) \
  GPU_ESPERA_MAXIMA_S=$(tf output -raw gpu_espera_maxima_s) \
  GCP_PROJECT_ID=$GCP_PROJECT_ID GOOGLE_IMPERSONATE_SERVICE_ACCOUNT=$GOOGLE_IMPERSONATE_SERVICE_ACCOUNT \
  scripts/testar-jobs-gpu.sh "${JOBS_GPU[@]}"

URL=$(tf output -raw url)
curl -sSf "$URL/v1/health" >/dev/null
echo "No ar: $URL (/v1/health respondeu 200)"
