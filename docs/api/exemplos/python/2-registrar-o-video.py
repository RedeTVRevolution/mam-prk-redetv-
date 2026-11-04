"""Passo 2: registra o vídeo e guarda o Job e a URL de upload em job.json.

Uso: URL=... CHAVE=... ARQUIVO=video.mp4 [PROGRAMA="TV Fama"] python 2-registrar-o-video.py
O nome precisa terminar em .mp4 (um .mov com conteúdo MP4 se envia com nome .mp4).
"""

import json
import os
import uuid
from pathlib import Path

import requests

arquivo = Path(os.environ["ARQUIVO"])
corpo = {
    "nome": arquivo.name,
    "tamanho_bytes": arquivo.stat().st_size,
    "tipo": "video/mp4",
}
if os.environ.get("PROGRAMA"):
    corpo["programa"] = os.environ["PROGRAMA"]

resposta = requests.post(
    f"{os.environ['URL']}/v1/jobs",
    json=corpo,
    headers={
        "X-API-Key": os.environ["CHAVE"],
        # Guarde a chave: para repetir o pedido (passo 7), use a mesma.
        "Idempotency-Key": os.environ.get("CHAVE_DE_IDEMPOTENCIA") or str(uuid.uuid4()),
    },
    timeout=30,
)
resposta.raise_for_status()
Path("job.json").write_text(json.dumps(resposta.json(), indent=2))
print(f"Job: {resposta.json()['id']} (status {resposta.status_code})")
