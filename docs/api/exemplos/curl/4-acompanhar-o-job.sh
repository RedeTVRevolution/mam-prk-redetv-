#!/usr/bin/env bash
# Passo 4: consulta o Job até ele terminar (concluido, falhou ou cancelado).
# Use o webhook em vez disto quando puder; a consulta é o plano B.
# Uso: URL=... CHAVE=... ./4-acompanhar-o-job.sh   (lê job.json)
set -euo pipefail

JOB_ID=$(jq -r .id job.json)
while true; do
  RESPOSTA=$(curl --fail-with-body -sS "$URL/v1/jobs/$JOB_ID" -H "X-API-Key: $CHAVE")
  ESTADO=$(printf '%s' "$RESPOSTA" | jq -r .estado)
  echo "$(date +%T) $ESTADO etapa=$(printf '%s' "$RESPOSTA" | jq -r .etapa_atual)"
  case "$ESTADO" in
    concluido) break ;;
    falhou) printf '%s' "$RESPOSTA" | jq '{estado, codigo_falha}'; exit 1 ;;
    cancelado) exit 1 ;;
  esac
  sleep 30
done
