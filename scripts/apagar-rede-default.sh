#!/usr/bin/env bash
# Usado pelo scripts/deploy-dev.sh (#301): apaga a rede `default` e as regras de firewall dela,
# se ainda existirem. Nada do MAM usa essa rede (os Jobs usam a mam-validacao), então o
# apply não precisa dela; se algo ainda a usasse, o gcloud recusaria apagar a rede e o
# deploy pararia. Só mexe em regras que estão na `default`. Roda como a mam-terraform
# (compute.securityAdmin para o firewall, compute.networkAdmin para a rede). É por gcloud e
# não por `import`: o `import` de um objeto que já foi apagado falharia em todo plan seguinte.
set -euo pipefail

: "${GCP_PROJECT_ID:?}"
: "${GOOGLE_IMPERSONATE_SERVICE_ACCOUNT:?}"
gc() { gcloud --project "$GCP_PROJECT_ID" --impersonate-service-account "$GOOGLE_IMPERSONATE_SERVICE_ACCOUNT" "$@"; }

# Por `list` e não `describe`: o describe falha igual sem a rede e sem permissão, e um erro
# de acesso não pode passar por "já não existe".
REDE=$(gc compute networks list --filter='name=default' --format='value(name)')
if [[ -z $REDE ]]; then
  echo "A rede default já não existe."
  exit 0
fi
REGRAS=$(gc compute firewall-rules list --filter='network~/networks/default$' --format='value(name)')
for regra in $REGRAS; do
  gc compute firewall-rules delete "$regra" --quiet
done
gc compute networks delete default --quiet
echo "A rede default e as regras dela foram apagadas."
