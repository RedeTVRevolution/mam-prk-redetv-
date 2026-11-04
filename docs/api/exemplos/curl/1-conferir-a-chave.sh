#!/usr/bin/env bash
# Passo 1: confere que a chave funciona. Responde o sistema e os escopos da chave.
# Uso: URL=https://... CHAVE=... ./1-conferir-a-chave.sh
set -euo pipefail

curl --fail-with-body -sS "$URL/v1/eu" -H "X-API-Key: $CHAVE"
echo
