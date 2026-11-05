#!/usr/bin/env bash
# Passo 2: registra o vídeo e guarda o Job e a URL de upload em job.json.
# Uso: URL=... CHAVE=... ARQUIVO=video.mp4 DATA_DE_EXIBICAO=AAAA-MM-DD [PROGRAMA="TV Fama"] ./2-registrar-o-video.sh
# O nome precisa terminar em .mp4 (um .mov com conteúdo MP4 se envia com nome .mp4).
set -euo pipefail

TAMANHO=$(wc -c < "$ARQUIVO" | tr -d ' ')
NOME=$(basename "$ARQUIVO")
CHAVE_DE_IDEMPOTENCIA=${CHAVE_DE_IDEMPOTENCIA:-$(uuidgen)}

jq -n --arg nome "$NOME" --argjson tamanho "$TAMANHO" --arg data "$DATA_DE_EXIBICAO" --arg programa "${PROGRAMA:-}" \
  '{nome: $nome, tamanho_bytes: $tamanho, tipo: "video/mp4", data_exibicao: $data}
   + (if $programa == "" then {} else {programa: $programa} end)' |
  curl --fail-with-body -sS -X POST "$URL/v1/jobs" \
    -H "X-API-Key: $CHAVE" \
    -H "Content-Type: application/json" \
    -H "Idempotency-Key: $CHAVE_DE_IDEMPOTENCIA" \
    --data @- | tee job.json
echo
echo "Job: $(jq -r .id job.json)"
