#!/usr/bin/env bash
# `make verificar`: falha se um nome de recurso da nuvem aparecer escrito em api/
# ou web/src/, fora dos testes. Nomes vêm sempre da configuração (AGENTS.md).
# Procura o ID do projeto (o formato do wizard e, se definido, o GCP_PROJECT_ID) e
# os nomes de bucket, pelos sufixos que o infra/modulos/mam/main.tf monta, mais o do estado do
# Terraform e o das fontes do build, que ficam fora da lista. Procura também, entre
# aspas, os nomes da busca (coleções e índices) e a região dela.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

sufixos=$(sed -n 's/^ *sufixos_dos_buckets *= *\[\(.*\)\]$/\1/p' infra/modulos/mam/main.tf | tr -d '" ' | tr ',' '|')
if [[ -z $sufixos ]]; then
  echo "checar-nomes-da-nuvem: sufixos_dos_buckets não encontrado em infra/modulos/mam/main.tf" >&2
  exit 1
fi
padrao="mam-redetv-[a-z0-9]|-($sufixos|tfstate|fontes)([^a-z0-9-]|$)"
busca=$(sed -nE -e 's/^ *(colecao_da_busca|colecao_de_texto_da_busca|colecao_de_medida_da_busca|indice_da_descricao) *= *"(.*)"$/\2/p' \
  -e '/^variable "regiao_da_busca"/,/^}/s/^ *default *= *"(.*)"$/\1/p' infra/modulos/mam/main.tf | paste -sd '|' -)
if [[ $(tr '|' '\n' <<<"$busca" | grep -c .) -ne 5 ]]; then
  echo "checar-nomes-da-nuvem: nomes da busca não encontrados em infra/modulos/mam/main.tf" >&2
  exit 1
fi
padrao+="|[\"']($busca)[\"']"
if [[ -n ${GCP_PROJECT_ID:-} ]]; then
  padrao+="|$GCP_PROJECT_ID"
fi

if grep -rnIE "$padrao" api web/src --exclude-dir=tests --exclude-dir=__pycache__ \
  --exclude='*.test.*' --exclude=setup-testes.ts; then
  echo "Nome de recurso da nuvem escrito no código (acima): leia da configuração." >&2
  exit 1
fi
