"""Passo 7: repete o registro do passo 2 com a mesma Idempotency-Key. Devolve o mesmo
Job com status 200 (o primeiro foi 202), sem criar outro.

Uso: URL=... CHAVE=... ARQUIVO=video.mp4 [PROGRAMA="TV Fama"] CHAVE_DE_IDEMPOTENCIA=<a do passo 2> \
     python 7-repetir-com-idempotencia.py
O corpo tem de ser o mesmo do passo 2 (inclusive o programa, se você o mandou); outro
corpo com a mesma chave dá 409.
"""

import os
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
        "Idempotency-Key": os.environ["CHAVE_DE_IDEMPOTENCIA"],
    },
    timeout=30,
)
print("status", resposta.status_code, resposta.json().get("id"))
