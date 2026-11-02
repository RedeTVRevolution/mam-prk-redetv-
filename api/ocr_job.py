"""Ponto de entrada do Cloud Run Job de OCR da tela.

O Workflows passa o id do Job em `JOB_ID`, depois da transcrição, com o Job em
`analisando`. O Job roda sem internet: o proxy vem do Storage e os modelos, da imagem.
Se a leitura falha, o Job vai a `falhou` pelo ciclo de vida e a execução também falha,
para o Workflows não seguir para a análise.
"""

import logging
import os
import time
from pathlib import Path

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api import teste_dos_jobs
from api.ciclo_de_vida import transitar
from api.jobs import RepositorioDeJobs
from api.jobs import agora_utc as agora
from api.leitura_da_tela import (
    LeitorDeQuadro,
    LeituraDaTela,
    LeiturasDoJob,
    LinhaLida,
    QuadroLido,
)
from api.mudanca_da_tela import MudancaDaTela, limiar_do_ambiente
from api.nuvem import LeiturasStorage, RepositorioFirestore
from api.paddle import LeitorPaddle, nome_do_modelo
from api.quadros import quadros_por_trecho

log = logging.getLogger(__name__)


def executar(
    job_id: str,
    repositorio: RepositorioDeJobs,
    armazenamento: LeiturasDoJob,
    leitor: LeitorDeQuadro,
    pasta: Path,
    limiar_de_mudanca: float = 0,
) -> None:
    """`limiar_de_mudanca` (`api/mudanca_da_tela.py`): 0 lê todos os quadros."""
    job = repositorio.obter(job_id)
    if job is None or job.estado != "analisando":
        return
    try:
        proxy = pasta / f"{job_id}.mp4"
        armazenamento.baixar_proxy(job_id, proxy)
        comeco = time.monotonic()
        mudanca = MudancaDaTela(limiar_de_mudanca)
        quadros: list[QuadroLido] = []
        linhas: list[LinhaLida] = []
        lidos = 0
        for inicio, do_trecho in quadros_por_trecho(proxy, pasta / "quadros"):
            for i, quadro in enumerate(do_trecho):
                # O quadro igual ao último lido repete a leitura dele.
                if mudanca.mudou(quadro):
                    linhas = leitor.ler(quadro)
                    lidos += 1
                quadros.append(QuadroLido(segundo=inicio + i, linhas=list(linhas)))
        log.info(
            "Leitura da tela: %d quadros lidos e %d pulados em %.0f s (limiar %s)",
            lidos,
            len(quadros) - lidos,
            time.monotonic() - comeco,
            limiar_de_mudanca,
        )
        armazenamento.gravar_leitura(
            job_id, LeituraDaTela(modelo=nome_do_modelo(), quadros=quadros)
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
    # O log do Job diz em qual dispositivo rodou (`api.whisper`, `api.paddle`, em INFO).
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("api").setLevel(logging.INFO)
    if teste_dos_jobs.ativo():
        # Teste depois da publicação (#238): amostra da imagem, nada no Storage nem no Firestore.
        raise SystemExit(teste_dos_jobs.testar_ocr())
    projeto = os.environ["GCP_PROJECT_ID"]
    executar(
        os.environ["JOB_ID"],
        RepositorioFirestore(firestore.Client(project=projeto)),
        LeiturasStorage(ClienteStorage(project=projeto), os.environ["BUCKET_ACEITOS"]),
        LeitorPaddle.da_pasta(os.environ["PASTA_DOS_MODELOS"]),
        Path(os.environ["TMPDIR"]),
        limiar_do_ambiente(),
    )


if __name__ == "__main__":
    main()
