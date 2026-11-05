#!/usr/bin/env bash
# Passo 7: repete o registro do passo 2 com a mesma Idempotency-Key. Devolve o mesmo
# Job com status 200 (o primeiro foi 202), sem criar outro.
# Uso: URL=... CHAVE=... ARQUIVO=video.mp4 DATA_DE_EXIBICAO=AAAA-MM-DD [PROGRAMA="TV Fama"] CHAVE_DE_IDEMPOTENCIA=<a do passo 2> ./7-repetir-com-idempotencia.sh
set -euo pipefail

TAMANHO=$(wc -c < "$ARQUIVO" | tr -d ' ')
NOME=$(basename "$ARQUIVO")

# O corpo tem de ser o mesmo do passo 2 (inclusive o programa, se você o mandou);
# outro corpo com a mesma chave dá 409.
jq -n --arg nome "$NOME" --argjson tamanho "$TAMANHO" --arg data "$DATA_DE_EXIBICAO" --arg programa "${PROGRAMA:-}" \
  '{nome: $nome, tamanho_bytes: $tamanho, tipo: "video/mp4", data_exibicao: $data}
   + (if $programa == "" then {} else {programa: $programa} end)' |
  curl -sS -o /dev/null -w 'status %{http_code}\n' -X POST "$URL/v1/jobs" \
    -H "X-API-Key: $CHAVE" \
    -H "Content-Type: application/json" \
    -H "Idempotency-Key: $CHAVE_DE_IDEMPOTENCIA" \
    --data @-
