"""Ponto de entrada do Cloud Run Job de OCR da tela.

O Workflows passa o id do Job em `JOB_ID`, depois da transcrição, com o Job em
`analisando`. O Job roda sem internet: o proxy vem do Storage e os modelos, da imagem.
Se a leitura falha, o Job vai a `falhou` pelo ciclo de vida e a execução também falha,
para o Workflows não seguir para a análise.
"""

import os
from pathlib import Path

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.ciclo_de_vida import transitar
from api.jobs import RepositorioDeJobs
from api.jobs import agora_utc as agora
from api.leitura_da_tela import (
    LeitorDeQuadro,
    LeituraDaTela,
    LeiturasDoJob,
    QuadroLido,
)
from api.nuvem import LeiturasStorage, RepositorioFirestore
from api.paddle import NOME_DO_MODELO, LeitorPaddle
from api.quadros import tirar_quadros


def executar(
    job_id: str,
    repositorio: RepositorioDeJobs,
    armazenamento: LeiturasDoJob,
    leitor: LeitorDeQuadro,
    pasta: Path,
) -> None:
    job = repositorio.obter(job_id)
    if job is None or job.estado != "analisando":
        return
    try:
        proxy = pasta / f"{job_id}.mp4"
        armazenamento.baixar_proxy(job_id, proxy)
        quadros = [
            QuadroLido(segundo=segundo, linhas=leitor.ler(quadro))
            for segundo, quadro in enumerate(tirar_quadros(proxy, pasta / "quadros"))
        ]
        armazenamento.gravar_leitura(
            job_id, LeituraDaTela(modelo=NOME_DO_MODELO, quadros=quadros)
        )
    except Exception:
        transitar(
            repositorio,
            job_id,
            "analisando",
            "falhou",
            agora(),
            codigo_falha="ocr_falhou",
        )
        raise


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    executar(
        os.environ["JOB_ID"],
        RepositorioFirestore(firestore.Client(project=projeto)),
        LeiturasStorage(ClienteStorage(project=projeto), os.environ["BUCKET_ACEITOS"]),
        LeitorPaddle.da_pasta(os.environ["PASTA_DOS_MODELOS"]),
        Path(os.environ["TMPDIR"]),
    )


if __name__ == "__main__":
    main()
