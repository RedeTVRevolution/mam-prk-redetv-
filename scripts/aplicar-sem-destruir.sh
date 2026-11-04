#!/usr/bin/env bash
# Usado pelo scripts/deploy-dev.sh (#292): roda o `plan` do infra/ com os argumentos
# recebidos e só aplica se o plano não destruir nem recriar nada. Uma recriação aparece
# como ação `delete` (junto com `create`), então basta procurar `delete`. Quem decidiu
# destruir de propósito roda de novo com PERMITIR_DESTRUICAO=sim. Aplica o plano gravado,
# o mesmo que foi conferido.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PLANO=$(mktemp)
PLANO_JSON=$(mktemp)
trap 'rm -f "$PLANO" "$PLANO_JSON"' EXIT
terraform -chdir=infra plan -input=false -out="$PLANO" "$@"
terraform -chdir=infra show -json "$PLANO" >"$PLANO_JSON"

DESTRUICOES=$(jq -r '.resource_changes[]? | select(.change.actions | index("delete")) | "\(.address) (\(.change.actions | join("+")))"' "$PLANO_JSON")
if [[ -n $DESTRUICOES && ${PERMITIR_DESTRUICAO:-} != sim ]]; then
  echo "O plano destrói ou recria recursos; nada foi aplicado:" >&2
  echo "$DESTRUICOES" | sed 's/^/  /' >&2
  echo "Se é de propósito, rode de novo com PERMITIR_DESTRUICAO=sim." >&2
  exit 1
fi
# Pré-voo (api/pre_voo.py): o que o plan cria ou muda vai às próprias APIs antes do apply
# (validateOnly, timeSeries, workflow descartável), como a conta do apply. Recusa = nada aplicado.
python3 -m api.pre_voo "$PLANO_JSON"
terraform -chdir=infra apply -input=false "$PLANO"
