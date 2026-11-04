"""Passo 6: confere a assinatura de um webhook recebido. Faça isto no seu receptor,
antes de confiar no corpo. A assinatura é o HMAC-SHA256, em hexadecimal, de
"<X-Webhook-Data>.<corpo exato>" com o segredo do seu sistema; recuse data com mais
de 5 minutos de diferença do seu relógio e guarde os `X-Webhook-Id` já vistos, porque
o mesmo evento pode chegar mais de uma vez.

Uso: SEGREDO=... DATA="$X_WEBHOOK_DATA" ASSINATURA="$X_WEBHOOK_ASSINATURA" \
     python 6-verificar-o-webhook.py corpo.json
"""

import hmac
import os
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

corpo = Path(sys.argv[1]).read_bytes()
data = os.environ["DATA"]
esperada = hmac.digest(
    os.environ["SEGREDO"].encode(), data.encode() + b"." + corpo, sha256
).hex()

enviada = datetime.fromisoformat(data)
if enviada.tzinfo is None or abs(datetime.now(UTC) - enviada) > timedelta(minutes=5):
    sys.exit("data fora da tolerância: responda 401 e ignore o evento")
if not hmac.compare_digest(esperada, os.environ["ASSINATURA"]):
    sys.exit("assinatura inválida: responda 401 e ignore o evento")
print("assinatura confere")
