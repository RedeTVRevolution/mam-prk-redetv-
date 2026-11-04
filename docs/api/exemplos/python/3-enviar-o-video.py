"""Passo 3: envia o arquivo pela URL de upload do passo 2 (upload retomável do Cloud
Storage: o POST abre a sessão, o PUT manda os bytes). Não precisa da chave de API.

Uso: ARQUIVO=video.mp4 python 3-enviar-o-video.py   (lê job.json)
"""

import json
import os
from pathlib import Path

import requests

arquivo = Path(os.environ["ARQUIVO"])
tamanho = arquivo.stat().st_size
job = json.loads(Path("job.json").read_text())

sessao = requests.post(
    job["url_de_upload"],
    headers={
        "Content-Type": "video/mp4",
        "x-goog-resumable": "start",
        "x-upload-content-length": str(tamanho),
    },
    timeout=60,
)
sessao.raise_for_status()
destino = sessao.headers["Location"]

# Se a conexão cair, pergunte quanto já chegou com
#   requests.put(destino, headers={"Content-Range": f"bytes */{tamanho}"})
# (308 e o cabeçalho Range: bytes=0-N) e mande o resto com
# Content-Range: bytes N+1-{tamanho - 1}/{tamanho}.
with arquivo.open("rb") as dados:
    enviado = requests.put(
        destino, data=dados, headers={"Content-Type": "video/mp4"}, timeout=3600
    )
enviado.raise_for_status()
print("Enviado. O Job passa a validando.")
