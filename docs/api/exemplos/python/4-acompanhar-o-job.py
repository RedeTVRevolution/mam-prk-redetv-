"""Passo 4: consulta o Job até ele terminar (concluido, falhou ou cancelado).
Use o webhook em vez disto quando puder; a consulta é o plano B.

Uso: URL=... CHAVE=... python 4-acompanhar-o-job.py   (lê job.json)
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

job_id = json.loads(Path("job.json").read_text())["id"]
while True:
    resposta = requests.get(
        f"{os.environ['URL']}/v1/jobs/{job_id}",
        headers={"X-API-Key": os.environ["CHAVE"]},
        timeout=30,
    )
    resposta.raise_for_status()
    job = resposta.json()
    print(time.strftime("%H:%M:%S"), job["estado"], job["etapa_atual"])
    if job["estado"] == "concluido":
        break
    if job["estado"] in ("falhou", "cancelado"):
        sys.exit(f"{job['estado']}: {job['codigo_falha']}")
    time.sleep(30)
