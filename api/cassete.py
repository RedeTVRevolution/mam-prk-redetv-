"""Cassete do Gemini: uma resposta real gravada, para o contrato rodar sem rede.

Uso: `make gravar-cassetes` (chama `python -m api.cassete` com o `.env`). Gera um
clipe sintético, passa pelo validador como um envio real, sobe o proxy no bucket
de aceitos do dev e faz a chamada real. O cassete guarda só o modelo, o vídeo e
o texto da resposta: nenhum cabeçalho, nenhuma credencial. Regrave sempre que
mudar o modelo ou o esquema.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud.storage import Client as ClienteStorage

from api.decupagem import Video
from api.gemini import (
    MODELO,
    Chamada,
    SessaoHttp,
    Transporte,
    TransporteVertex,
    analisar,
)
from api.validador import validar

CASSETE = Path(__file__).parent / "tests" / "cassetes" / "gemini_sintetico.json"
OBJETO = "cassetes/sintetico.mp4"


class _Gravador:
    """Guarda o último texto; `analisar` só retorna depois de validar esse texto."""

    def __init__(self, transporte: Transporte) -> None:
        self._transporte = transporte
        self.texto = ""

    def gerar(self, chamada: Chamada) -> str:
        self.texto = self._transporte.gerar(chamada)
        return self.texto


def gravar(
    transporte: Transporte, *, video_uri: str, video: Video, destino: Path = CASSETE
) -> None:
    gravador = _Gravador(transporte)
    analisar(gravador, video_uri=video_uri, job_id="cassete", video=video)
    destino.parent.mkdir(parents=True, exist_ok=True)
    cassete = {
        "modelo": MODELO,
        "video": video.model_dump(exclude_none=True),
        "texto": gravador.texto,
    }
    destino.write_text(json.dumps(cassete, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    with tempfile.TemporaryDirectory() as pasta:
        clipe = Path(pasta) / "sintetico.mp4"
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=30",
                "-f", "lavfi", "-i", "sine=duration=30",
                "-c:v", "libx264", "-c:a", "aac", str(clipe),
            ],
            check=True,
        )  # fmt: skip
        aceito = validar(clipe, Path(pasta) / "saida")
        bucket = ClienteStorage(project=projeto).bucket(f"{projeto}-aceitos")
        bucket.blob(OBJETO).upload_from_filename(
            str(aceito.proxy), content_type="video/mp4"
        )
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = cast(SessaoHttp, AuthorizedSession(credenciais))  # type: ignore[no-untyped-call]
    gravar(
        TransporteVertex(projeto, sessao),
        video_uri=f"gs://{projeto}-aceitos/{OBJETO}",
        video=Video(sha256=aceito.sha256, duracao_ms=round(aceito.duracao_s * 1000)),
    )
    print(f"Cassete gravado em {CASSETE}")


if __name__ == "__main__":
    main()
