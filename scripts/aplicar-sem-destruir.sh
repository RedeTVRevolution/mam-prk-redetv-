#!/usr/bin/env bash
# Usado pelo scripts/deploy-dev.sh (#292): roda o `plan` do infra/ com os argumentos
# recebidos e só aplica se o plano não destruir nem recriar nada. Uma recriação aparece
# como ação `delete` (junto com `create`), então basta procurar `delete`. Quem decidiu
# destruir de propósito roda de novo com PERMITIR_DESTRUICAO=sim. Aplica o plano gravado,
# o mesmo que foi conferido.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PLANO=$(mktemp)
trap 'rm -f "$PLANO"' EXIT
terraform -chdir=infra plan -input=false -out="$PLANO" "$@"

DESTRUICOES=$(terraform -chdir=infra show -json "$PLANO" |
  jq -r '.resource_changes[]? | select(.change.actions | index("delete")) | "\(.address) (\(.change.actions | join("+")))"')
if [[ -n $DESTRUICOES && ${PERMITIR_DESTRUICAO:-} != sim ]]; then
  echo "O plano destrói ou recria recursos; nada foi aplicado:" >&2
  echo "$DESTRUICOES" | sed 's/^/  /' >&2
  echo "Se é de propósito, rode de novo com PERMITIR_DESTRUICAO=sim." >&2
  exit 1
fi
terraform -chdir=infra apply -input=false "$PLANO"
