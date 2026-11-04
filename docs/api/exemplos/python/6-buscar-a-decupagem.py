"""Passo 6: busca a decupagem do Job concluído e a salva em decupagem.json.

Uso: URL=... CHAVE=... python 6-buscar-a-decupagem.py   (lê job.json)
"""

import json
import os
from pathlib import Path

import requests

job_id = json.loads(Path("job.json").read_text())["id"]
resposta = requests.get(
    f"{os.environ['URL']}/v1/jobs/{job_id}/decupagem",  # o requests já aceita gzip
    headers={"X-API-Key": os.environ["CHAVE"]},
    timeout=60,
)
resposta.raise_for_status()
decupagem = resposta.json()
Path("decupagem.json").write_text(json.dumps(decupagem, indent=2, ensure_ascii=False))
print(decupagem["versao_esquema"], len(decupagem["pautas"]), "pautas")
