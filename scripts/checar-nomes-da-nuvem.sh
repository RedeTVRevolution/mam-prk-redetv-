#!/usr/bin/env bash
# `make verificar`: falha se um nome de recurso da nuvem aparecer escrito em api/
# ou web/src/, fora dos testes. Nomes vêm sempre da configuração (AGENTS.md).
# Procura o ID do projeto (o formato do wizard e, se definido, o GCP_PROJECT_ID) e
# os nomes de bucket, pelos sufixos que o infra/main.tf monta, mais o do estado do
# Terraform e o das fontes do build, que ficam fora da lista.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

sufixos=$(sed -n 's/^ *sufixos_dos_buckets *= *\[\(.*\)\]$/\1/p' infra/main.tf | tr -d '" ' | tr ',' '|')
if [[ -z $sufixos ]]; then
  echo "checar-nomes-da-nuvem: sufixos_dos_buckets não encontrado em infra/main.tf" >&2
  exit 1
fi
padrao="mam-redetv-[a-z0-9]|-($sufixos|tfstate|fontes)([^a-z0-9-]|$)"
if [[ -n ${GCP_PROJECT_ID:-} ]]; then
  padrao+="|$GCP_PROJECT_ID"
fi

if grep -rnIE "$padrao" api web/src --exclude-dir=tests --exclude-dir=__pycache__ \
  --exclude='*.test.*' --exclude=setup-testes.ts --exclude=render-teste.tsx; then
  echo "Nome de recurso da nuvem escrito no código (acima): leia da configuração." >&2
  exit 1
fi
