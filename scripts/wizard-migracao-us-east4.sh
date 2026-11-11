#!/usr/bin/env bash
#
# Wizard da troca do MAM de southamerica-east1 para us-east4 e da remoção de SP (#538, spec #535).
# Uma pessoa roda uma vez; cada passo mostra o comando, pede confirmação e confere o resultado.
# Dá para retomar: o último passo concluído fica em .migracao-us-east4/passo.
# Segue o formato dos wizards (biblioteca de UX abaixo, copiada do scripts/wizard-gcp-dev.sh,
# sem as funções que este não usa); a lógica pura fica entre MIGRACAO_LOGICA_INICIO e _FIM, e é
# testada em api/tests/test_wizard_migracao_us_east4.py.

# shellcheck disable=SC2329 # as funções são chamadas por nome (passo_N) e de dentro de run_wizard
set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Wizard library: delightful, consistent UX, identical across every wizard.
# ──────────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""
fi

# Author sets this at the top of the stages section.
TOTAL_STAGES=0

_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()    # KEYs written to ENV_FILE this run
SKIPPED=()        # things we couldn't do (e.g. gh missing)

# _clear wipes the terminal so only the current step is on screen. No-op when
# output isn't a terminal, so piped logs stay readable.
_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1 && tput clear 2>/dev/null; then return 0; fi
  printf '\033[2J\033[3J\033[H'
}

# banner "Title" shows the opening frame: what this wizard does.
banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later, since it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

# stage "Name" clears the screen, then announces a stage and shows progress.
# Clearing keeps only the current step on screen.
stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

# say "..." prints a plain instruction line.
say()  { printf '  %s\n' "$1"; }
# step "..." is a numbered-feeling action the human takes in the browser.
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

# open_url URL opens it in the human's browser, cross-platform incl. WSL.
open_url() {
  local url="$1"
  printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
  { if   command -v wslview     >/dev/null 2>&1; then wslview "$url"
    elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url"
    elif command -v xdg-open    >/dev/null 2>&1; then xdg-open "$url"
    elif command -v open        >/dev/null 2>&1; then open "$url"
    else false; fi
  } >/dev/null 2>&1 || warn "couldn't open a browser, so visit it manually: $url"
}

# pause "msg" waits for the human to confirm they've done the manual part.
pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ </dev/tty || true
}

# confirm "question" is a y/N gate; returns success on yes.
confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply </dev/tty || true
  [[ "$reply" =~ ^[Yy] ]]
}

# _existing KEY: current value of KEY in ENV_FILE, if any, with write_env's single
# quotes or a plain dotenv double-quoted value undone.
_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line value sq="'\\''"; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  value="${line#*=}"
  if [[ "$value" == \'*\' ]]; then value="${value:1:${#value}-2}"; value="${value//"$sq"/\'}"
  elif [[ "$value" == \"*\" ]]; then
    value="${value:1:${#value}-2}"
    [[ "$value" == *[\\\$\"]* ]] && return 1   # escapes, $ or ": can't decode safely; ask again
  fi
  printf '%s' "$value"
}

# ask KEY "Prompt" reads a value into $KEY. Offers the existing .env value as
# a default on re-runs (Enter keeps it). Visible input (non-secret), edited
# with Readline. Fails at EOF with no input.
ask() {
  local key="$1" prompt="$2" current input s=$'\001' e=$'\002' p rc=0
  current=$(_existing "$key" || true)
  # Readline needs the colour codes wrapped in \001..\002 to place the cursor.
  p="  $s$BOLD$e$prompt$s$RESET$e "
  [[ -n "$current" ]] && p+="${s}${DIM}${e}[Enter keeps current]${s}${RESET}${e} "
  read -e -r -p "$p" input || rc=1
  if (( rc )) && [[ -z "$input" ]]; then return 1; fi
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

# write_env KEY VALUE upserts KEY='VALUE' into ENV_FILE (replaces any existing
# line) and sets $KEY. Idempotent. Creates ENV_FILE at mode 0600; writes through
# a symlink and keeps an existing file's mode.
write_env() {
  local key="$1" value="$2" tmp sq="'\\''"
  [[ -e "$ENV_FILE" ]] || (umask 077 && : > "$ENV_FILE")
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf "%s='%s'\n" "$key" "${value//\'/$sq}" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
  printf -v "$key" '%s' "$value"
  WRITTEN_ENV+=("$key")
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

# set_var NAME VALUE sets a GitHub Actions repo variable (non-secret).
set_var() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh variable set "$name" --body "$value" >/dev/null 2>&1; then
      printf '  %s✓ set%s GitHub variable %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub variable $name")
  warn "skipped GitHub variable $name, gh not ready; set it later"
}

# finish mostra o resumo no fim.
finish() {
  _clear
  printf '\n%s%s  ✓ Troca para us-east4 concluída%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} )) && note "gravei ${#WRITTEN_ENV[@]} valor(es) em $ENV_FILE: ${WRITTEN_ENV[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "ainda falta, à mão:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# Lógica pura, sem nuvem: testada em api/tests/test_wizard_migracao_us_east4.py.
# ──────────────────────────────────────────────────────────────────────────

# MIGRACAO_LOGICA_INICIO

# enderecos_do_arquivo ARQUIVO: os endereços do Terraform a tirar do estado (a lista do #537),
# um por linha, sem comentário (#) nem linha em branco. Arquivo ausente ou vazio é erro.
enderecos_do_arquivo() {
  local lista
  [[ -f "$1" ]] || { echo "Falta $1 (a lista de endereços do #537)." >&2; return 1; }
  lista=$(sed -e 's/#.*$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^$/d' "$1")
  [[ -n "$lista" ]] || { echo "$1 não tem nenhum endereço." >&2; return 1; }
  printf '%s\n' "$lista"
}

# enderecos_no_estado ESTADO: dos endereços lidos na entrada, só os que o estado ainda tem
# (ESTADO = saída do `terraform state list`), com ou sem índice [..]. Deixa o passo repetível:
# `state rm` num endereço que já saiu daria erro e não tiraria nenhum.
enderecos_no_estado() {
  awk 'NR == FNR { estado[++n] = $0; next }
       { for (i = 1; i <= n; i++)
           if (estado[i] == $0 || index(estado[i], $0 "[") == 1 || index(estado[i], $0 ".") == 1) { print; break } }' "$1" -
}

# normalizar TEXTO: minúsculas, `_` vira `-`, sem o prefixo `bucket-` (BUCKET_ACEITOS = aceitos).
normalizar() {
  local t
  t=$(printf '%s' "$1" | tr '[:upper:]_' '[:lower:]-')
  printf '%s' "${t#bucket-}"
}

# pares_por_papel NOVOS_JSON ANTIGO...: liga cada recurso novo (mapa papel → nome, do output do
# Terraform) ao antigo que tem o mesmo papel: o nome igual ao papel ou terminado em `-papel`
# (`_` vale como `-`). Imprime "papel antigo novo", o papel normalizado. Erro se um papel não
# achar nenhum antigo, ou achar mais de um: nada de adivinhar qual copiar.
pares_por_papel() {
  local novos=$1 papel novo chave antigo nome achados
  shift
  jq -e 'type == "object" and length > 0' <<<"$novos" >/dev/null 2>&1 \
    || { echo "O mapa dos recursos novos está vazio ou não é JSON." >&2; return 1; }
  while IFS=$'\t' read -r papel novo; do
    chave=$(normalizar "$papel")
    achados=()
    for antigo in "$@"; do
      [[ "$antigo" != "$novo" ]] || continue
      nome=$(normalizar "$antigo")
      if [[ "$nome" == "$chave" || "$nome" == *"-$chave" ]]; then achados+=("$antigo"); fi
    done
    case ${#achados[@]} in
      1) printf '%s %s %s\n' "$chave" "${achados[0]}" "$novo" ;;
      0) echo "Nenhum recurso antigo combina com '$papel' (novo: $novo)." >&2; return 1 ;;
      *) echo "Mais de um recurso antigo combina com '$papel': ${achados[*]}." >&2; return 1 ;;
    esac
  done < <(jq -r 'to_entries[] | [.key, .value] | @tsv' <<<"$novos")
}

# banco_principal_antigo SEGURANCA: o banco do Firestore antigo que não é o de segurança.
# Lê na entrada os bancos que estão na região antiga; exige exatamente um além do de segurança.
banco_principal_antigo() {
  local restantes
  restantes=$(grep -vxF -- "$1" | sed '/^$/d' || true)
  if [[ -z "$restantes" || "$(printf '%s\n' "$restantes" | grep -c .)" -ne 1 ]]; then
    echo "Esperava um banco antigo além de '$1'; achei: ${restantes:-nenhum}." >&2
    return 1
  fi
  printf '%s\n' "$restantes"
}

# comparar_contagens ANTIGAS NOVAS: cada arquivo tem "chave valor..." por linha. Imprime uma
# linha por chave (ok, DIFERE ou FALTA) e sai com erro se qualquer uma não bater.
comparar_contagens() {
  awk -v so_crescem=" ${CONTAGENS_QUE_SO_CRESCEM:-} " '
       FILENAME == ARGV[1] { a[$1] = substr($0, length($1) + 2); next }
       { b[$1] = substr($0, length($1) + 2) }
       END {
         for (k in a) todas[k] = 1
         for (k in b) todas[k] = 1
         for (k in todas) {
           if (!(k in a)) { printf "FALTA   %s: só no novo (%s)\n", k, b[k]; ruim = 1 }
           else if (!(k in b)) { printf "FALTA   %s: só no antigo (%s)\n", k, a[k]; ruim = 1 }
           else if (index(so_crescem, " " k " ") && b[k] + 0 >= a[k] + 0) printf "ok      %s: antigo %s | novo %s (só cresce)\n", k, a[k], b[k]
           else if (a[k] != b[k]) { printf "DIFERE  %s: antigo %s | novo %s\n", k, a[k], b[k]; ruim = 1 }
           else printf "ok      %s: %s\n", k, a[k]
         }
         exit ruim
       }' "$1" "$2" | LC_ALL=C sort
}

# contagens_que_cairam ANTES DEPOIS: as chaves de ANTES cujo valor (um número) em DEPOIS é menor
# ou nem existe; sai com erro se houver alguma. Para o que só cresce, como a exportação do
# faturamento: o que a cópia trouxe não pode sumir.
contagens_que_cairam() {
  awk '
       FILENAME == ARGV[1] { antes[$1] = $2; next }
       { depois[$1] = $2 }
       END {
         for (k in antes)
           if (!(k in depois) || depois[k] + 0 < antes[k] + 0) {
             printf "%s: eram %s, agora %s\n", k, antes[k], (k in depois) ? depois[k] : "(sumiu)"; ruim = 1
           }
         exit ruim
       }' "$1" "$2"
}

# contagem_do_bucket BUCKET: "objetos bytes" do bucket, pelo TOTAL do `gcloud storage ls -l`.
# Bucket vazio é "0 0"; qualquer outro erro (permissão, bucket que não existe) para.
contagem_do_bucket() {
  local saida erro
  erro=$(mktemp)
  if saida=$(gcloud storage ls --recursive --long "gs://$1/**" 2>"$erro"); then
    rm -f "$erro"
    printf '%s\n' "$saida" | sed -n 's/^TOTAL: \([0-9]*\) objects, \([0-9]*\) bytes.*/\1 \2/p' | tail -n 1
  elif grep -q 'matched no objects' "$erro"; then
    rm -f "$erro"
    echo "0 0"
  else
    cat "$erro" >&2
    rm -f "$erro"
    return 1
  fi
}

# MIGRACAO_LOGICA_FIM

# ler_lista lê a entrada, uma linha por item, na variável global LISTA (sem linhas vazias).
LISTA=()
# Lê a política IAM do projeto na entrada e imprime "membro|papel|titulo|expressao" de cada condição
# presa ao banco. Filtra pela expressão: o título na nuvem (so-o-banco-default) não é o do Terraform novo.
condicoes_do_banco() { # PROJETO BANCO
  jq -r --arg e "resource.name == \"projects/$1/databases/$2\"" \
    '.bindings[] | select(.condition.expression == $e)
     | .role as $r | .condition.title as $t | .condition.expression as $x | .members[] | "\(.)|\($r)|\($t)|\($x)"'
}

ler_lista() {
  local linha
  LISTA=()
  while IFS= read -r linha; do
    [[ -z "$linha" ]] || LISTA+=("$linha")
  done
}

# rodar COMANDO...: mostra o comando, pede confirmação e roda. Falha do comando para o wizard
# (set -e); rodar de novo retoma do passo em que parou.
rodar() {
  printf '  %s$ %s%s\n' "$DIM" "$*" "$RESET"
  confirm "Rodar?" || { warn "Parei aqui. Rode o wizard de novo para retomar deste passo."; exit 1; }
  "$@"
}

# ──────────────────────────────────────────────────────────────────────────
# Fontes na documentação oficial (conferidas em 10/11/2026):
# - Firestore, exportar e importar: o bucket do export fica "perto" do banco; os dados de um banco
#   entram em outro; o export não leva índice (o Terraform cria os do banco novo).
#   https://docs.cloud.google.com/firestore/native/docs/manage-data/export-import
# - Firestore, mover dados: na importação, se o bucket está numa localização diferente da do banco
#   de destino, é preciso mover os arquivos para um bucket na mesma localização do destino. Por isso
#   o wizard exporta num bucket de SP (a localização do banco de origem), copia para o bucket novo e
#   importa de lá.
#   https://docs.cloud.google.com/firestore/native/docs/manage-data/move-data
# - Firestore, proteção contra exclusão: `gcloud firestore databases update --no-delete-protection`
#   e depois `gcloud firestore databases delete`.
#   https://docs.cloud.google.com/firestore/native/docs/manage-databases
# - BigQuery, cópia de dataset entre regiões (Data Transfer Service, `cross_region_copy`): não copia
#   views, rotinas nem tabelas externas (o Terraform cria as views); não anexa em tabela de destino,
#   só a troca por completo (`overwrite_destination_table`); permite `bq mk --transfer_run`.
#   https://docs.cloud.google.com/bigquery/docs/copying-datasets
#   https://docs.cloud.google.com/bigquery/docs/working-with-transfers
# - KMS: `gcloud kms keys versions destroy` agenda a destruição (30 dias por padrão); key ring e
#   chave não se apagam: só a versão.
#   https://docs.cloud.google.com/kms/docs/destroy-restore
# ──────────────────────────────────────────────────────────────────────────

run_wizard() {

TOTAL_STAGES=11

cd "$(git rev-parse --show-toplevel)"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi
: "${GCP_PROJECT_ID:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${BUCKET_ESTADO_TF:?rode antes o scripts/wizard-gcp-dev.sh}"
: "${ADMINS_EMERGENCIA:?ponha no .env os e-mails dos administradores de emergência (o plan precisa)}"
P="$GCP_PROJECT_ID"
# Os dois nomes de região só existem neste wizard, que faz a troca uma vez.
REGIAO_ANTIGA="${REGIAO_ANTIGA:-southamerica-east1}"
REGIAO_NOVA="${REGIAO_NOVA:-us-east4}"
# Lista de endereços que o #537 deixa para tirar do estado antes do apply.
ENDERECOS="${ENDERECOS:-infra/migracao-us-east4/enderecos-recriados.txt}"
# Bucket (por papel) que leva os arquivos do export do Firestore. Não pode ser o da quarentena:
# o gatilho do Eventarc dispara a cada objeto novo nele.
PAPEL_DO_EXPORT="${PAPEL_DO_EXPORT:-referencias}"
# Papéis de bucket que não têm dado a copiar (as fontes do Cloud Build são refeitas a cada build).
PAPEIS_SEM_COPIA="${PAPEIS_SEM_COPIA:-fontes}"
# Datasets cuja contagem só se mostra: a exportação do faturamento continua gravando no dataset
# velho até o passo 7, então as linhas nunca batem exatas.
DATASETS_SO_INFORMATIVOS="${DATASETS_SO_INFORMATIVOS:-faturamento}"
# Contagens que só podem crescer: a aplicação nova já grava auditoria no banco novo depois da cópia.
CONTAGENS_QUE_SO_CRESCEM="${CONTAGENS_QUE_SO_CRESCEM:-seguranca:auditoria}"
DIR_ESTADO="${DIR_ESTADO:-.migracao-us-east4}"
(umask 077 && mkdir -p "$DIR_ESTADO")
ARQ_PASSO="$DIR_ESTADO/passo"
SAIDAS_ANTIGAS="$DIR_ESTADO/saidas-antigas.json"

# A config do gcloud do MAM (criada pelo wizard-gcp-dev.sh); o gcloud e o bq rodam como você
# (Owner), o Terraform impersona a mam-terraform pelo GOOGLE_IMPERSONATE_SERVICE_ACCOUNT do .env.
export CLOUDSDK_ACTIVE_CONFIG_NAME="${CLOUDSDK_ACTIVE_CONFIG_NAME:-mam-dev}"
export CLOUDSDK_CORE_PROJECT="$P"
tf() { terraform -chdir=infra "$@"; }
VARS_DAS_IMAGENS=(-var imagem=pendente -var imagem_validacao=pendente -var imagem_transcricao_gpu=pendente
  -var imagem_ocr_gpu=pendente -var imagem_objetos=pendente)

# Recursos de uma região, descobertos na nuvem: nada de nome escrito aqui.
buckets_da_regiao() { # REGIAO [EXCETO]
  gcloud storage buckets list --format=json | jq -r --arg r "$1" --arg e "${2:-}" \
    '.[] | select((.location | ascii_downcase) == $r and .name != $e) | .name'
}
datasets_da_regiao() { # REGIAO
  local ds loc
  for ds in $(bq --project_id "$P" ls --format=json --max_results=1000 | jq -r '.[]?.datasetReference.datasetId'); do
    loc=$(bq --project_id "$P" show --format=json "$P:$ds" | jq -r '.location | ascii_downcase')
    [[ "$loc" != "$1" ]] || echo "$ds"
  done
}
bancos_da_regiao() { # REGIAO
  gcloud firestore databases list --format=json | jq -r --arg r "$1" \
    '.[] | select(.locationId == $r) | .name | split("/") | last'
}
tabelas_do_dataset() { # DATASET REGIAO PAPEL: "papel.tabela linhas" (só tabelas, sem views)
  bq --project_id "$P" query --nouse_legacy_sql --location="$2" --format=csv \
    "SELECT table_id, row_count FROM \`$P.$1\`.__TABLES__ WHERE type = 1" \
    | tail -n +2 | awk -F, -v papel="$3" 'NF == 2 { print papel "." $1, $2 }'
}
documentos_do_banco() { # BANCO PAPEL: "papel:colecao documentos", só as coleções da raiz
  # O MAM não usa subcoleções (nenhum `.collection()` encadeado em api/).
  uv run --locked python - "$P" "$1" "$2" <<'PY'
import sys
from google.cloud import firestore

projeto, banco, papel = sys.argv[1:4]
cliente = firestore.Client(project=projeto, database=banco)
for colecao in cliente.collections():
    print(f"{papel}:{colecao.id}", colecao.count().get()[0][0].value)
PY
}
agendas_da_regiao() { # REGIAO: os jobs do Cloud Scheduler
  gcloud scheduler jobs list --location "$1" --format='value(name.basename())'
}
pausar_agendas() { # REGIAO: pausa todos os jobs do Scheduler da região (repetir não muda nada)
  local a
  for a in $(agendas_da_regiao "$1"); do
    gcloud scheduler jobs pause "$a" --location "$1" >/dev/null
    printf '  %s✓%s agenda %s pausada em %s\n' "$GREEN" "$RESET" "$a" "$1"
  done
}
retomar_agendas() { # REGIAO
  local a
  for a in $(agendas_da_regiao "$1"); do
    gcloud scheduler jobs resume "$a" --location "$1" >/dev/null
    printf '  %s✓%s agenda %s retomada em %s\n' "$GREEN" "$RESET" "$a" "$1"
  done
}
pares_de_buckets() { # imprime "papel antigo novo" para os buckets novos do Terraform
  local antigos=()
  while IFS= read -r b; do antigos+=("$b"); done < <(buckets_da_regiao "$REGIAO_ANTIGA" "$BUCKET_ESTADO_TF")
  pares_por_papel "$(tf output -json buckets)" "${antigos[@]}"
}
pares_de_datasets() {
  local antigos=()
  while IFS= read -r d; do antigos+=("$d"); done < <(datasets_da_regiao "$REGIAO_ANTIGA")
  pares_por_papel "$(tf output -json datasets_bigquery)" "${antigos[@]}"
}
pares_de_bancos() { # "principal antigo novo" e "seguranca antigo novo"
  local seguranca principal
  seguranca=$(jq -r '.banco_de_seguranca.value // empty' "$SAIDAS_ANTIGAS")
  if [[ -z "$seguranca" ]]; then
    ask SEGURANCA_ANTIGA "Nome do banco de segurança em $REGIAO_ANTIGA (não achei no estado antigo):" || exit 1
    seguranca=$SEGURANCA_ANTIGA
  fi
  principal=$(bancos_da_regiao "$REGIAO_ANTIGA" | banco_principal_antigo "$seguranca")
  printf 'principal %s %s\n' "$principal" "$(tf output -raw banco_firestore)"
  printf 'seguranca %s %s\n' "$seguranca" "$(tf output -raw banco_de_seguranca)"
}

# ── Os passos ────────────────────────────────────────────────────────────

passo_1() {
  say "Confiro o git e o ambiente, e peço o que só uma pessoa sabe."
  [[ "$REGIAO_ANTIGA" != "$REGIAO_NOVA" ]] || { warn "As duas regiões são $REGIAO_NOVA."; exit 1; }
  [[ "${PERMITIR_DESTRUICAO:-}" != sim ]] \
    || { warn "PERMITIR_DESTRUICAO=sim está no ambiente: tire e rode de novo. O plan só pode criar."; exit 1; }
  gcloud config configurations describe "$CLOUDSDK_ACTIVE_CONFIG_NAME" >/dev/null 2>&1 \
    || { warn "Falta a config gcloud $CLOUDSDK_ACTIVE_CONFIG_NAME: rode o scripts/wizard-gcp-dev.sh."; exit 1; }
  git fetch --quiet origin main
  [[ "$(git rev-parse --abbrev-ref HEAD)" == main && "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] \
    || { warn "Fique na main, igual à origin/main, com o PR da troca já mesclado."; exit 1; }
  [[ -z "$(git status --porcelain)" ]] || { warn "A árvore do git tem mudanças; limpe antes."; exit 1; }
  printf '  %s✓%s main igual à origin/main\n' "$GREEN" "$RESET"
  # Execuções ainda correndo nos Workflows antigos.
  local ativos=0 w n
  for w in $(gcloud workflows list --location "$REGIAO_ANTIGA" --format='value(name.basename())'); do
    n=$(gcloud workflows executions list "$w" --location "$REGIAO_ANTIGA" --filter='state=ACTIVE' \
      --format='value(name)' | grep -c . || true)
    ativos=$((ativos + n))
  done
  (( ativos == 0 )) || { warn "$ativos execução(ões) ativa(s) nos Workflows de $REGIAO_ANTIGA. Espere acabar."; exit 1; }
  printf '  %s✓%s nenhuma execução ativa nos Workflows de %s\n' "$GREEN" "$RESET" "$REGIAO_ANTIGA"
  confirm "Nenhum vídeo está em processamento (Jobs de GPU e de CPU parados)?" || exit 1
  confirm "O envio de vídeos está parado até o fim da cópia?" || exit 1
  note "O merge na main dispara o job publicar do CD. Ele vai falhar no plan (recriar recurso conta como"
  note "destruição) e isso é o esperado: quem publica a troca é este wizard, no passo 3."
}

passo_2() {
  say "Tiro do estado do Terraform o que será recriado em $REGIAO_NOVA; o plan só pode criar."
  local arquivos lista f estado
  rodar terraform -chdir=infra init -input=false -backend-config="bucket=$BUCKET_ESTADO_TF"
  # Os nomes antigos (banco de segurança etc.): depois do apply o output já traz os novos.
  [[ -s "$SAIDAS_ANTIGAS" ]] || (umask 077 && tf output -json >"$SAIDAS_ANTIGAS")
  note "Nomes de antes da troca guardados em $SAIDAS_ANTIGAS."
  write_env GCP_REGION "$REGIAO_NOVA"
  gcloud config set compute/region "$REGIAO_NOVA" >/dev/null 2>&1
  export TF_VAR_projeto="$P" TF_VAR_regiao="$REGIAO_NOVA" TF_VAR_admins_emergencia="$ADMINS_EMERGENCIA"

  arquivos=$(enderecos_do_arquivo "$ENDERECOS")
  estado=$(mktemp)
  tf state list >"$estado"
  lista=$(enderecos_no_estado "$estado" <<<"$arquivos")
  rm -f "$estado"
  # Antes de qualquer cópia, nada em SP pode escrever: as agendas (purga, taxa diária) saem do ar.
  # Elas só voltam a existir, pausadas, em SP até o passo 10 as apagar. Nenhum Job roda sozinho:
  # eles só correm quando uma agenda, o Workflows ou a web os chama.
  say "Pauso as agendas do Cloud Scheduler de $REGIAO_ANTIGA para nada escrever lá durante a cópia."
  confirm "Pausar?" || exit 1
  pausar_agendas "$REGIAO_ANTIGA"
  if [[ -n "$lista" ]]; then
    # O CD (job publicar) lê GCP_REGION ao começar. Com a região antiga e o estado sem estes
    # endereços, o plan dele criaria tudo de novo em $REGIAO_ANTIGA sem destruir nada, e o apply
    # passaria. Por isso a variável troca antes do state rm: um run que a leia nova com o estado
    # ainda inteiro quer recriar (aplicar-sem-destruir.sh recusa). E os que já leram a antiga
    # têm de acabar antes. A conferência fica aqui para valer também na retomada.
    set_var GCP_REGION "$REGIAO_NOVA"
    [[ " ${SKIPPED[*]-} " != *"GitHub variable GCP_REGION"* ]] \
      || { warn "Sem trocar GCP_REGION no GitHub o state rm não é seguro (gh auth login)."; exit 1; }
    local rodando
    rodando=$(gh run list --workflow ci.yml --branch main --limit 20 --json status \
      --jq '[.[] | select(.status != "completed")] | length') \
      || { warn "Não consegui ler os runs do CI pelo gh (gh auth login)."; exit 1; }
    (( rodando == 0 )) \
      || { warn "$rodando run(s) do CI na main ainda correndo (leram a região antiga). Espere acabar e rode de novo."; exit 1; }
    printf '  %s✓%s nenhum run do CI na main correndo\n' "$GREEN" "$RESET"
    say "Estes endereços saem do estado (os recursos de $REGIAO_ANTIGA continuam na nuvem até o passo 10):"
    printf '%s\n' "$lista" | while IFS= read -r f; do step "$f"; done
    (umask 077 && tf state pull >"$DIR_ESTADO/estado-antes.tfstate")
    note "Cópia do estado antes: $DIR_ESTADO/estado-antes.tfstate"
    confirm "Tirar estes $(printf '%s\n' "$lista" | grep -c .) endereço(s) do estado?" || exit 1
    printf '%s\n' "$lista" | while IFS= read -r f; do tf state rm "$f"; done
  else
    note "Nenhum endereço da lista está no estado (já saíram)."
  fi
  set_var GCP_REGION "$REGIAO_NOVA" # repetir não muda nada (retomada sem endereços a tirar)

  local plano json apagam
  plano=$(mktemp); json=$(mktemp)
  tf plan -input=false -out="$plano" "${VARS_DAS_IMAGENS[@]}"
  tf show -json "$plano" >"$json"
  say "O plan, por ação:"
  jq -r '[.resource_changes[]? | .change.actions | join("+")] | group_by(.) | map("  \(.[0]): \(length)") | .[]' "$json"
  apagam=$(jq -r '.resource_changes[]? | select(.change.actions | index("delete")) | .address' "$json")
  rm -f "$plano" "$json"
  if [[ -n "$apagam" ]]; then
    warn "O plan destrói ou recria, e a troca não pode:"
    printf '%s\n' "$apagam" | sed 's/^/    /'
    note "Falta o endereço na lista do #537? Acrescente em $ENDERECOS e rode de novo."
    exit 1
  fi
  printf '  %s✓%s o plan só cria e atualiza\n' "$GREEN" "$RESET"
}

passo_3() {
  say "make deploy-dev cria tudo em $REGIAO_NOVA (pelo apply sem destruição). O make publicar"
  say "do ticket é o deploy-dev: é ele que roda no CD."
  export TF_VAR_projeto="$P" TF_VAR_regiao="$REGIAO_NOVA" TF_VAR_admins_emergencia="$ADMINS_EMERGENCIA"
  rodar make deploy-dev
  [[ "$(tf output -raw regiao)" == "$REGIAO_NOVA" ]] \
    || { warn "O output regiao do Terraform não é $REGIAO_NOVA. Confira o apply."; exit 1; }
  printf '  %s✓%s Terraform em %s\n' "$GREEN" "$RESET" "$REGIAO_NOVA"
  write_env FIRESTORE_BANCO "$(tf output -raw banco_firestore)"
  write_env FIRESTORE_BANCO_DE_SEGURANCA "$(tf output -raw banco_de_seguranca)"
  local papel nome chave
  while IFS=$'\t' read -r papel nome; do
    chave="BUCKET_$(normalizar "$papel" | tr '[:lower:]-' '[:upper:]_')"
    write_env "$chave" "$nome"
  done < <(tf output -json buckets | jq -r 'to_entries[] | [.key, .value] | @tsv')
  # O resto (datasets etc.) o Makefile lê do Terraform; só troca o que o .env já guarda.
  if _existing BIGQUERY_DATASET >/dev/null; then write_env BIGQUERY_DATASET "$(tf output -raw bigquery_dataset)"; fi
  # As agendas novas nascem rodando: pausadas até a cópia e a conferência acabarem (passo 9),
  # senão a purga ou a taxa diária mexeriam nos bancos e buckets novos no meio da cópia.
  say "Pauso as agendas novas de $REGIAO_NOVA até a conferência das contagens."
  pausar_agendas "$REGIAO_NOVA"
  note "Os bancos e os buckets novos existem, vazios. Os dados vêm nos próximos passos."
}

passo_4() {
  say "Firestore: export de cada banco de $REGIAO_ANTIGA e import no banco novo."
  say "A documentação pede, na importação, um bucket na localização do banco de destino. Então o export"
  say "vai para um bucket de $REGIAO_ANTIGA, é copiado para o bucket novo e importado de lá."
  local pares_b velho_b novo_b banco antigo novo prefixo
  pares_b=$(pares_de_buckets)
  velho_b=$(awk -v p="$(normalizar "$PAPEL_DO_EXPORT")" '$1 == p { print $2 }' <<<"$pares_b")
  novo_b=$(awk -v p="$(normalizar "$PAPEL_DO_EXPORT")" '$1 == p { print $3 }' <<<"$pares_b")
  [[ -n "$velho_b" && -n "$novo_b" ]] || { warn "Sem par de buckets para o papel $PAPEL_DO_EXPORT."; exit 1; }
  while read -r banco antigo novo; do
    prefixo="migracao-firestore/$novo-$(date -u +%Y%m%dT%H%M%SZ)"
    say "Banco $banco: $antigo → $novo (via $prefixo)"
    rodar gcloud firestore export "gs://$velho_b/$prefixo" --database="$antigo"
    rodar gcloud storage rsync --recursive "gs://$velho_b/$prefixo" "gs://$novo_b/$prefixo"
    rodar gcloud firestore import "gs://$novo_b/$prefixo/" --database="$novo"
  done < <(pares_de_bancos)
  say "Limpo os arquivos do export nos dois buckets."
  rodar gcloud storage rm --recursive "gs://$velho_b/migracao-firestore/"
  rodar gcloud storage rm --recursive "gs://$novo_b/migracao-firestore/"
  note "O import não leva índice nem TTL: eles vêm do Terraform, que já os criou nos bancos novos."
}

passo_5() {
  say "Storage: cada bucket antigo é copiado para o novo (rsync, sem apagar nada)."
  local pares papel antigo novo n
  pares=$(pares_de_buckets)
  while read -r papel antigo novo; do
    [[ " $PAPEIS_SEM_COPIA " != *" $papel "* ]] || continue
    step "$papel: gs://$antigo → gs://$novo"
  done <<<"$pares"
  confirm "Estes são os pares certos?" || exit 1
  while read -r papel antigo novo; do
    [[ " $PAPEIS_SEM_COPIA " != *" $papel "* ]] || continue
    if [[ "$papel" == quarentena ]]; then
      read -r n _ <<<"$(contagem_do_bucket "$antigo")"
      if (( n > 0 )); then
        warn "A quarentena antiga tem $n objeto(s): copiar no bucket novo dispara o Eventarc, que"
        warn "manda cada um para o pipeline em $REGIAO_NOVA."
        confirm "Copiar mesmo assim?" || continue
      fi
    fi
    rodar gcloud storage rsync --recursive "gs://$antigo" "gs://$novo"
  done <<<"$pares"
  note "O rsync copia as versões atuais; versões antigas dos objetos ficam em $REGIAO_ANTIGA."
}

passo_6() {
  say "BigQuery: cópia de cada dataset entre regiões, pelo Data Transfer Service."
  say "As views e as tabelas do Terraform já existem nos datasets novos: a cópia troca as tabelas"
  say "(overwrite_destination_table) e não leva view."
  local pares papel antigo novo params cfg loc estado i
  [[ -n "$(gcloud services list --enabled --filter='config.name=bigquerydatatransfer.googleapis.com' --format='value(config.name)')" ]] \
    || { warn "A API bigquerydatatransfer não está ligada (o Terraform a liga no passo 3)."; exit 1; }
  pares=$(pares_de_datasets)
  while read -r papel antigo novo; do step "$papel: $P:$antigo ($REGIAO_ANTIGA) → $P:$novo ($REGIAO_NOVA)"; done <<<"$pares"
  confirm "Estes são os pares certos?" || exit 1
  # A lista vem pelo descritor 3: o bq pede o version_info no terminal e não pode ler a lista.
  while read -r papel antigo novo <&3; do
    params=$(jq -cn --arg d "$antigo" --arg p "$P" \
      '{source_dataset_id: $d, source_project_id: $p, overwrite_destination_table: "true"}')
    printf '  %s$ bq mk --transfer_config --no_auto_scheduling --data_source=cross_region_copy --target_dataset=%s ...%s\n' \
      "$DIM" "$novo" "$RESET"
    confirm "Copiar $antigo → $novo?" || exit 1
    cfg=$(bq --project_id "$P" mk --transfer_config --no_auto_scheduling --data_source=cross_region_copy \
      --target_dataset="$novo" --display_name="migracao-us-east4-$antigo" --params="$params" \
      --service_account_name="${GOOGLE_IMPERSONATE_SERVICE_ACCOUNT:?falta no .env}" \
      | tee /dev/stderr | grep -o "projects/[^']*" | head -n 1)
    [[ -n "$cfg" ]] || { warn "Não achei o nome da transferência na resposta do bq."; exit 1; }
    loc=${cfg#*/locations/}; loc=${loc%%/*}
    bq --project_id "$P" mk --transfer_run --run_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$cfg"
    estado=PENDING
    for i in $(seq 1 360); do
      estado=$(bq --project_id "$P" ls --transfer_run --transfer_location="$loc" --format=json --max_results=1 "$cfg" \
        | jq -r '.[0].state // "PENDING"')
      printf '  %s%s: %s (%s)%s\n' "$DIM" "$antigo" "$estado" "$i" "$RESET"
      [[ "$estado" != SUCCEEDED && "$estado" != FAILED && "$estado" != CANCELLED ]] || break
      sleep 20
    done
    [[ "$estado" == SUCCEEDED ]] \
      || { warn "A cópia de $antigo terminou em $estado. A transferência $cfg ficou para você ver no console."; exit 1; }
    bq --project_id "$P" rm -f --transfer_config "$cfg"
    printf '  %s✓%s %s copiado\n' "$GREEN" "$RESET" "$antigo"
  done 3<<<"$pares"
  # O que a cópia trouxe dos datasets de exportação: o passo 8 confere que nada disso some depois
  # que a exportação nova passa a gravar ali.
  : >"$DIR_ESTADO/copiado-so-informativo.txt"
  while read -r papel antigo novo; do
    [[ " $DATASETS_SO_INFORMATIVOS " == *" $papel "* ]] || continue
    tabelas_do_dataset "$novo" "$REGIAO_NOVA" "$papel" >>"$DIR_ESTADO/copiado-so-informativo.txt"
  done <<<"$pares"
  note "Faça o passo 7 logo e nunca rode a cópia de novo com overwrite depois dele: ela apagaria o que"
  note "a exportação do faturamento gravou no dataset novo."
}

passo_7() {
  local conta
  conta=$(gcloud billing projects describe "$P" --format='value(billingAccountName)')
  conta="${conta#billingAccounts/}"
  say "Passo manual: apontar a exportação de custos para o dataset novo."
  open_url "https://console.cloud.google.com/billing/$conta/export"
  step "Cada tipo de exportação (detalhada de uso e padrão, os que estiverem ligados): a documentação manda"
  step "DESLIGAR a exportação, escolher o tipo de novo e escolher o projeto $P e o dataset novo (o de $REGIAO_NOVA;"
  step "o nome sai de: terraform -chdir=infra output datasets_bigquery); depois salvar."
  note "O que a documentação diz (docs.cloud.google.com/billing/docs/how-to/export-data-bigquery-setup):"
  note "- dado exportado antes não é recarregado no dataset novo, e num dataset regional só entra o uso"
  note "  a partir da data em que a exportação foi ligada: a história de $REGIAO_ANTIGA vem só da cópia do"
  note "  passo 6, então a cópia não duplica com recarga;"
  note "- linhas inseridas à mão podem ser apagadas pelo processo da exportação: o passo 8 confere que o"
  note "  que a cópia trouxe continua lá e que nenhuma linha se repetiu."
  pause "Enter quando a exportação estiver apontando para o dataset novo"
}

passo_8() {
  say "Contagens lado a lado: objetos e bytes por bucket, documentos por coleção, linhas por tabela."
  local antigas novas papel antigo novo
  # Dataset de exportação do faturamento: a exportação antiga e a nova gravam fora de sincronia, então
  # as linhas não batem exatas. Confere o que importa: o que a cópia trouxe não sumiu (a contagem
  # só cresce) e nenhuma linha se repetiu (uma recarga da exportação duplicaria).
  conferir_exportacao() { # PAPEL DATASET_NOVO
    local agora t repetidas n
    agora=$(mktemp)
    tabelas_do_dataset "$2" "$REGIAO_NOVA" "$1" >"$agora"
    note "Exportação $1, linhas agora: $(tr '\n' ';' <"$agora")"
    if ! contagens_que_cairam "$DIR_ESTADO/copiado-so-informativo.txt" "$agora"; then
      warn "Linhas que a cópia trouxe sumiram do dataset novo (acima). Nada será apagado."
      exit 1
    fi
    while read -r t n; do
      repetidas=$(bq --project_id "$P" query --nouse_legacy_sql --location="$REGIAO_NOVA" --format=csv \
        "SELECT COUNT(*) - COUNT(DISTINCT TO_JSON_STRING(t)) FROM \`$P.$2.${t#*.}\` AS t" | tail -n 1)
      if [[ "$repetidas" != 0 ]]; then
        warn "${t#*.}: $repetidas linha(s) repetida(s). A exportação nova recarregou dado já copiado?"
        confirm "Seguir assim mesmo (o painel de custo contaria em dobro)?" || exit 1
      fi
    done <"$agora"
    rm -f "$agora"
  }
  antigas=$(mktemp); novas=$(mktemp)
  local pares
  pares=$(pares_de_buckets)
  while read -r papel antigo novo; do
    [[ " $PAPEIS_SEM_COPIA " != *" $papel "* ]] || continue
    echo "bucket:$papel $(contagem_do_bucket "$antigo")" >>"$antigas"
    echo "bucket:$papel $(contagem_do_bucket "$novo")" >>"$novas"
  done <<<"$pares"
  while read -r papel antigo novo; do
    documentos_do_banco "$antigo" "$papel" >>"$antigas"
    documentos_do_banco "$novo" "$papel" >>"$novas"
  done < <(pares_de_bancos)
  pares=$(pares_de_datasets)
  while read -r papel antigo novo; do
    if [[ " $DATASETS_SO_INFORMATIVOS " == *" $papel "* ]]; then
      conferir_exportacao "$papel" "$novo"
      continue
    fi
    tabelas_do_dataset "$antigo" "$REGIAO_ANTIGA" "$papel" >>"$antigas"
    tabelas_do_dataset "$novo" "$REGIAO_NOVA" "$papel" >>"$novas"
  done <<<"$pares"
  if comparar_contagens "$antigas" "$novas"; then
    printf '  %s✓%s tudo bate\n' "$GREEN" "$RESET"
    rm -f "$antigas" "$novas"
  else
    warn "Alguma contagem não bate (acima). Nada será apagado. Os arquivos: $antigas e $novas"
    exit 1
  fi
}

passo_9() {
  local url
  url=$(tf output -raw url)
  say "Passo manual: login na URL nova e um vídeo inteiro pelo pipeline, em $REGIAO_NOVA."
  open_url "$url"
  step "Entre com uma conta (o login e o segundo fator TOTP funcionam na URL nova)."
  step "Envie um vídeo e espere ele passar por todas as etapas, até a decupagem e a busca."
  note "Se o domínio ainda aponta para o IP antigo, o infra/README.md diz como mudar o registro A."
  confirm "O login e o vídeo inteiro funcionaram em $REGIAO_NOVA?" || { warn "Nada de SP foi apagado."; exit 1; }
  say "Com as contagens conferidas e o vídeo passando, as agendas de $REGIAO_NOVA voltam a rodar."
  confirm "Retomar as agendas (purga, taxa diária) em $REGIAO_NOVA?" || { SKIPPED+=("Retomar as agendas do Cloud Scheduler em $REGIAO_NOVA (gcloud scheduler jobs resume)"); return 0; }
  retomar_agendas "$REGIAO_NOVA"
}

# apagar_grupo TITULO FUNCAO ITEM...: mostra os itens, confirma e apaga um a um.
apagar_grupo() {
  local titulo=$1 funcao=$2 item
  shift 2
  if (( $# == 0 )); then note "$titulo: nada em $REGIAO_ANTIGA."; return 0; fi
  say "$titulo em $REGIAO_ANTIGA:"
  for item in "$@"; do step "$item"; done
  if ! confirm "Apagar estes $# item(ns)?"; then
    warn "Pulado: $titulo."
    SKIPPED+=("Apagar $titulo em $REGIAO_ANTIGA")
    return 0
  fi
  for item in "$@"; do "$funcao" "$item"; done
}

passo_10() {
  say "Apaga tudo de $REGIAO_ANTIGA, por gcloud e uma vez só (ADR 0019). Cada grupo mostra a lista e pede"
  say "confirmação. O bucket do estado do Terraform fica para o passo 11."
  confirm "O passo 9 deu certo e posso apagar $REGIAO_ANTIGA?" || exit 1
  local L=$REGIAO_ANTIGA ring chave versao

  apaga_gatilho() { gcloud eventarc triggers delete "$1" --location "$L" --quiet; }
  ler_lista < <(gcloud eventarc triggers list --location "$L" --format='value(name.basename())')
  apagar_grupo "Gatilhos do Eventarc" apaga_gatilho ${LISTA[@]+"${LISTA[@]}"}

  apaga_agenda() { gcloud scheduler jobs delete "$1" --location "$L" --quiet; }
  ler_lista < <(gcloud scheduler jobs list --location "$L" --format='value(name.basename())')
  apagar_grupo "Jobs do Scheduler" apaga_agenda ${LISTA[@]+"${LISTA[@]}"}

  apaga_workflow() { gcloud workflows delete "$1" --location "$L" --quiet; }
  ler_lista < <(gcloud workflows list --location "$L" --format='value(name.basename())')
  apagar_grupo "Workflows" apaga_workflow ${LISTA[@]+"${LISTA[@]}"}

  apaga_servico() { gcloud run services delete "$1" --region "$L" --quiet; }
  ler_lista < <(gcloud run services list --region "$L" --format='value(metadata.name)')
  apagar_grupo "Serviços do Cloud Run" apaga_servico ${LISTA[@]+"${LISTA[@]}"}

  apaga_job() { gcloud run jobs delete "$1" --region "$L" --quiet; }
  ler_lista < <(gcloud run jobs list --region "$L" --format='value(metadata.name)')
  apagar_grupo "Jobs do Cloud Run" apaga_job ${LISTA[@]+"${LISTA[@]}"}

  # A sub-rede dos Jobs de SP só sai depois dos Jobs; a rede em si é global e a de $REGIAO_NOVA a usa.
  apaga_subrede() { gcloud compute networks subnets delete "$1" --region "$L" --quiet; }
  ler_lista < <(gcloud compute networks subnets list --regions "$L" --format='value(name)')
  apagar_grupo "Sub-redes (a mam-validacao de SP)" apaga_subrede ${LISTA[@]+"${LISTA[@]}"}

  apaga_repositorio() { gcloud artifacts repositories delete "$1" --location "$L" --quiet; }
  ler_lista < <(gcloud artifacts repositories list --location "$L" --format='value(name.basename())')
  apagar_grupo "Repositórios do Artifact Registry" apaga_repositorio ${LISTA[@]+"${LISTA[@]}"}

  # O Model Armor só responde no endpoint da região; o global nega o acesso.
  local armor="https://modelarmor.$L.rep.googleapis.com/"
  apaga_modelo() { CLOUDSDK_API_ENDPOINT_OVERRIDES_MODELARMOR="$armor" gcloud model-armor templates delete "$1" --location "$L" --quiet; }
  ler_lista < <(CLOUDSDK_API_ENDPOINT_OVERRIDES_MODELARMOR="$armor" gcloud model-armor templates list --location "$L" --format='value(name.basename())')
  apagar_grupo "Modelos do Model Armor" apaga_modelo ${LISTA[@]+"${LISTA[@]}"}

  apaga_bucket() { gcloud storage rm --recursive --all-versions "gs://$1"; }
  ler_lista < <(buckets_da_regiao "$L" "$BUCKET_ESTADO_TF")
  apagar_grupo "Buckets" apaga_bucket ${LISTA[@]+"${LISTA[@]}"}

  # As consultas agendadas do BigQuery moram na região do dataset e seguem rodando sem ele.
  apaga_transferencia() { bq --project_id "$P" rm -f --transfer_config "$1"; }
  ler_lista < <(bq --project_id "$P" ls --transfer_config --transfer_location="$L" --format=json 2>/dev/null | jq -r '.[]?.name' 2>/dev/null)
  apagar_grupo "Transferências e consultas agendadas do BigQuery" apaga_transferencia ${LISTA[@]+"${LISTA[@]}"}

  apaga_dataset() { bq --project_id "$P" rm -r -f -d "$P:$1"; }
  ler_lista < <(datasets_da_regiao "$L")
  apagar_grupo "Datasets do BigQuery" apaga_dataset ${LISTA[@]+"${LISTA[@]}"}

  # As condições antigas do IAM do projeto (title so-o-banco-default; o novo é so-o-banco-principal) valem só para o banco principal
  # de SP. O state rm do passo 2 as soltou do Terraform e elas ficaram na nuvem. Só entram as que citam
  # o banco antigo: as sem condição e as do banco novo são as que o Terraform criou de novo.
  local principal_antigo politica
  # Sem banco antigo (passo repetido depois de apagá-lo) não sobra condição a tirar.
  principal_antigo=$(pares_de_bancos 2>/dev/null | awk '$1 == "principal" { print $2 }') || principal_antigo=""
  politica=$(gcloud projects get-iam-policy "$P" --format=json)
  apaga_condicao() { # "membro|papel|titulo|expressao"
    local membro papel titulo expressao arq
    IFS='|' read -r membro papel titulo expressao <<<"$1"
    arq=$(mktemp)
    jq -n --arg t "$titulo" --arg e "$expressao" '{title: $t, expression: $e}' >"$arq"
    gcloud projects remove-iam-policy-binding "$P" --member="$membro" --role="$papel" \
      --condition-from-file="$arq" >/dev/null
    rm -f "$arq"
  }
  ler_lista < <(condicoes_do_banco "$P" "$principal_antigo" <<<"$politica")
  apagar_grupo "Condições antigas do IAM no banco principal de $L" apaga_condicao ${LISTA[@]+"${LISTA[@]}"}

  apaga_banco() {
    gcloud firestore databases update --database="$1" --no-delete-protection
    gcloud firestore databases delete --database="$1" --quiet
  }
  ler_lista < <(bancos_da_regiao "$L")
  apagar_grupo "Bancos do Firestore" apaga_banco ${LISTA[@]+"${LISTA[@]}"}

  apaga_copia() { gcloud firestore backups delete --backup="$1" --location="$L" --quiet; }
  ler_lista < <(gcloud firestore backups list --location="$L" --format='value(name.basename())')
  apagar_grupo "Backups do Firestore" apaga_copia ${LISTA[@]+"${LISTA[@]}"}

  # O key ring e a chave não se apagam (o Google não deixa); só as versões se destroem.
  apaga_versao() {
    IFS=/ read -r ring chave versao <<<"$1"
    gcloud kms keys versions destroy "$versao" --key "$chave" --keyring "$ring" --location "$L"
  }
  LISTA=()
  for ring in $(gcloud kms keyrings list --location "$L" --format='value(name.basename())'); do
    for chave in $(gcloud kms keys list --keyring "$ring" --location "$L" --format='value(name.basename())'); do
      for versao in $(gcloud kms keys versions list --key "$chave" --keyring "$ring" --location "$L" \
        --filter='state=ENABLED OR state=DISABLED' --format='value(name.basename())'); do
        LISTA+=("$ring/$chave/$versao")
      done
    done
  done
  apagar_grupo "Versões de chave do KMS (o key ring fica)" apaga_versao ${LISTA[@]+"${LISTA[@]}"}
}

passo_11() {
  say "Por último, o estado do Terraform vai para um bucket em $REGIAO_NOVA e o antigo é apagado."
  local velho=$BUCKET_ESTADO_TF novo="${BUCKET_ESTADO_TF}-${REGIAO_NOVA}" n
  if [[ "$velho" == "$novo" ]]; then
    warn "O estado já está em $novo."
    return 0
  fi
  if ! gcloud storage buckets describe "gs://$novo" >/dev/null 2>&1; then
    rodar gcloud storage buckets create "gs://$novo" --location "$REGIAO_NOVA" \
      --uniform-bucket-level-access --public-access-prevention
    gcloud storage buckets update "gs://$novo" --versioning --update-labels app=mam
  fi
  rodar terraform -chdir=infra init -input=false -migrate-state -force-copy -backend-config="bucket=$novo"
  n=$(tf state list | grep -c . || true)
  (( n > 0 )) || { warn "O estado novo está vazio; não apaguei o antigo."; exit 1; }
  printf '  %s✓%s estado em gs://%s (%s recursos)\n' "$GREEN" "$RESET" "$novo" "$n"
  write_env BUCKET_ESTADO_TF "$novo"
  set_var BUCKET_ESTADO_TF "$novo"
  rodar gcloud storage rm --recursive --all-versions "gs://$velho"
  SKIPPED+=("Atualizar o GCP_REGION e o BUCKET_ESTADO_TF das variáveis do repositório, se o gh não estava pronto")
}

NOMES=("" "Pré-condições" "Estado do Terraform: só criar" "Criar tudo em $REGIAO_NOVA" "Firestore: export e import"
  "Storage: copiar os buckets" "BigQuery: copiar os datasets" "Faturamento: nova exportação (manual)"
  "Contagens lado a lado" "Login e vídeo inteiro (manual)" "Apagar $REGIAO_ANTIGA" "Estado do Terraform em $REGIAO_NOVA")

set -E
trap 'warn "O passo falhou. Corrija e rode de novo: ele retoma deste passo." >&2' ERR

FEITO=0
[[ ! -f "$ARQ_PASSO" ]] || FEITO=$(<"$ARQ_PASSO")
banner "Troca do MAM para $REGIAO_NOVA (spec #535, ticket #538)"
(( FEITO == 0 )) || note "Retomando: os passos até o $FEITO já foram feitos (apague $ARQ_PASSO para recomeçar)."
for n in 1 2 3 4 5 6 7 8 9 10 11; do
  stage "${NOMES[$n]}"
  if (( n <= FEITO )); then
    note "já feito"
    continue
  fi
  "passo_$n"
  echo "$n" >"$ARQ_PASSO"
  (( n == TOTAL_STAGES )) || pause "Enter para continuar"
done
finish

}

run_wizard "$@"; exit
