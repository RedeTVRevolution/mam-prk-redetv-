"""Cassetes reais para os contratos rodarem sem rede.

Uso: `make gravar-cassetes` (chama `python -m api.cassete` com o `.env` e o nome
do bucket de clipes-ouro que o Terraform monta). Gera um clipe sintético, passa
pelo validador como um envio real, sobe o proxy nesse bucket, sob `cassetes/`, e
faz a chamada real. O cassete guarda só o modelo, a versão que a Vertex informou,
o vídeo, o texto da resposta e o SHA-256 da instrução: nenhum cabeçalho, nenhuma
credencial. Regrave sempre que mudar o modelo, o esquema ou a instrução.

Também grava o pedido de texto da busca e a contagem de resultados (#507).
`make gravar-cassete-da-busca` regrava só esse contrato.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol, cast

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud.storage import Client as ClienteStorage

from api import gemini  # lido na chamada, para o teste trocar `INSTRUCAO`
from api.agent_retrieval import (
    AgentRetrieval,
    ConfigDaBusca,
    pedido_de_busca,
    transporte_http,
)
from api.agent_retrieval import Transporte as TransporteDaBusca
from api.decupagem import Video
from api.gemini import (
    MODELO,
    Chamada,
    SessaoHttp,
    Transporte,
    TransporteVertex,
    analisar,
)
from api.indice_da_busca import Consulta
from api.numero import com_as_formas
from api.validador import validar

CASSETE = Path(__file__).parent / "tests" / "cassetes" / "gemini_sintetico.json"
CASSETE_DA_BUSCA = Path(__file__).parent / "tests" / "cassetes" / "busca_formas.json"
OBJETO = "cassetes/sintetico.mp4"


def instrucao_sha256() -> str:
    """SHA-256 (hex) do texto de `INSTRUCAO`, antes de `instrucao()` preenchê-lo."""
    return hashlib.sha256(gemini.INSTRUCAO.encode("utf-8")).hexdigest()


class _Gravador:
    """Guarda o último texto; `analisar` só retorna depois de validar esse texto."""

    def __init__(self, transporte: Transporte) -> None:
        self._transporte = transporte
        self.texto = ""

    def gerar(self, chamada: Chamada) -> str:
        self.texto = self._transporte.gerar(chamada)
        return self.texto


class TransporteComVersao(Transporte, Protocol):
    versao_do_modelo: str


def gravar(
    transporte: TransporteComVersao,
    *,
    video_uri: str,
    video: Video,
    destino: Path = CASSETE,
) -> None:
    gravador = _Gravador(transporte)
    analisar(gravador, video_uri=video_uri, job_id="cassete", video=video)
    if not transporte.versao_do_modelo:
        raise RuntimeError("a Vertex não informou a versão do modelo")
    destino.parent.mkdir(parents=True, exist_ok=True)
    cassete = {
        "modelo": MODELO,
        "versao_do_modelo": transporte.versao_do_modelo,
        "video": video.model_dump(exclude_none=True),
        "texto": gravador.texto,
        "instrucao_sha256": instrucao_sha256(),
    }
    destino.write_text(json.dumps(cassete, ensure_ascii=False, indent=2) + "\n")


def gravar_busca(
    config: ConfigDaBusca,
    transporte: TransporteDaBusca,
    *,
    destino: Path = CASSETE_DA_BUSCA,
) -> None:
    """Grava o pedido e quantos resultados a busca real devolveu, sem dados da nuvem."""
    consulta = Consulta(texto=com_as_formas("gravata"))
    pedido = pedido_de_busca(config, consulta)
    resultados = AgentRetrieval(config, transporte).buscar(consulta)
    if not resultados:
        raise RuntimeError("a busca por gravata não devolveu nenhum resultado")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(
            {"origem": "nuvem", "pedido": pedido, "resultados": len(resultados)},
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    if sys.argv[1:] == ["busca"]:
        gravar_busca(ConfigDaBusca.do_ambiente(os.environ), transporte_http())
        print(f"Cassete gravado em {CASSETE_DA_BUSCA}")
        return
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
        bucket = ClienteStorage(project=projeto).bucket(
            os.environ["BUCKET_CLIPES_OURO"]
        )
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
        video_uri=f"gs://{bucket.name}/{OBJETO}",
        video=Video(sha256=aceito.sha256, duracao_ms=round(aceito.duracao_s * 1000)),
    )
    print(f"Cassete gravado em {CASSETE}")


if __name__ == "__main__":
    main()
