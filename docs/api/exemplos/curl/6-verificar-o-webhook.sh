#!/usr/bin/env bash
# Passo 6: confere a assinatura de um webhook recebido. Faça isto no seu receptor,
# antes de confiar no corpo. A assinatura é o HMAC-SHA256, em hexadecimal, de
# "<X-Webhook-Data>.<corpo exato>" com o segredo do seu sistema.
# Uso: SEGREDO=... DATA="$X_WEBHOOK_DATA" ASSINATURA="$X_WEBHOOK_ASSINATURA" \
#      ./6-verificar-o-webhook.sh corpo.json
set -euo pipefail

CORPO=$1
ESPERADA=$(printf '%s.%s' "$DATA" "$(cat "$CORPO")" |
  openssl dgst -sha256 -hmac "$SEGREDO" -hex | awk '{print $NF}')

if [ "$ESPERADA" != "$ASSINATURA" ]; then
  echo "assinatura inválida: responda 401 e ignore o evento" >&2
  exit 1
fi
# Recuse também uma data com mais de 5 minutos de diferença do seu relógio.
echo "assinatura confere"
