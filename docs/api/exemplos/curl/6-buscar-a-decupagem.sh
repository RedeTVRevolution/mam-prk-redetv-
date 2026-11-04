#!/usr/bin/env bash
# Passo 6: busca a decupagem do Job concluído e a salva em decupagem.json.
# Uso: URL=... CHAVE=... ./6-buscar-a-decupagem.sh   (lê job.json)
set -euo pipefail

JOB_ID=$(jq -r .id job.json)
curl --fail-with-body -sS --compressed "$URL/v1/jobs/$JOB_ID/decupagem" \
  -H "X-API-Key: $CHAVE" -o decupagem.json
jq '{versao_esquema, pautas: (.pautas | length), falas: (.transcricao | length)}' decupagem.json
