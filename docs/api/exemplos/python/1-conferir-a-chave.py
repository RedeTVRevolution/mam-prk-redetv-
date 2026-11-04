"""Passo 1: confere que a chave funciona e mostra o sistema e os escopos dela.

Uso: URL=https://... CHAVE=... python 1-conferir-a-chave.py
"""

import os

import requests

resposta = requests.get(
    f"{os.environ['URL']}/v1/eu",
    headers={"X-API-Key": os.environ["CHAVE"]},
    timeout=30,
)
resposta.raise_for_status()
print(resposta.json())
