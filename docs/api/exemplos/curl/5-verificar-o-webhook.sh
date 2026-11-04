#!/usr/bin/env bash
# Passo 5: confere a assinatura de um webhook recebido. Faça isto no seu receptor,
# antes de confiar no corpo. A assinatura é o HMAC-SHA256, em hexadecimal, de
# "<X-Webhook-Data>.<corpo exato>" com o segredo do seu sistema.
# Uso: SEGREDO=... DATA="$X_WEBHOOK_DATA" ASSINATURA="$X_WEBHOOK_ASSINATURA" \
#      ./5-verificar-o-webhook.sh corpo.json
set -euo pipefail

CORPO=$1
# O corpo vai direto do arquivo para o HMAC: $(cat) cortaria quebras de linha do fim.
ESPERADA=$({ printf '%s.' "$DATA"; cat "$CORPO"; } |
  openssl dgst -sha256 -hmac "$SEGREDO" -hex | awk '{print $NF}')

# A data tem de estar a menos de 5 minutos do seu relógio (date do GNU).
DIFERENCA=$(( $(date +%s) - $(date -d "$DATA" +%s) ))
if [ "${DIFERENCA#-}" -gt 300 ]; then
  echo "data fora da tolerância: responda 401 e ignore o evento" >&2
  exit 1
fi
# Aqui a comparação é simples; no receptor, compare em tempo constante
# (hmac.compare_digest no Python, crypto.timingSafeEqual no Node).
if [ "$ESPERADA" != "$ASSINATURA" ]; then
  echo "assinatura inválida: responda 401 e ignore o evento" >&2
  exit 1
fi
echo "assinatura confere"
