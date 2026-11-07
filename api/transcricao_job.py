"""Ponto de entrada do Cloud Run Job de transcrição.

O Workflows passa o id do Job em `JOB_ID`, depois da validação, com o Job em
`analisando`. O Job roda sem internet: o áudio vem do Storage e o modelo, da imagem.
Se a transcrição falha, o Job vai a `falhou` pelo ciclo de vida e a execução também
falha, para o Workflows não seguir para a análise.
"""

import logging
import os
from pathlib import Path

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api import log_estruturado, teste_dos_jobs
from api.ciclo_de_vida import transitar
from api.eventos_do_job import jobs_do_ambiente
from api.jobs import RepositorioDeJobs
from api.jobs import agora_utc as agora
from api.nuvem import TranscricoesStorage
from api.transcricao import Transcricao, TranscricoesDoJob, Transcritor
from api.whisper import IDIOMA, NOME_DO_MODELO, TranscritorFasterWhisper


def executar(
    job_id: str,
    repositorio: RepositorioDeJobs,
    armazenamento: TranscricoesDoJob,
    transcritor: Transcritor,
    pasta: Path,
) -> None:
    job = repositorio.obter(job_id)
    if job is None or job.estado != "analisando":
        return
    try:
        audio = pasta / f"{job_id}.wav"
        if armazenamento.baixar_audio(job_id, audio):
            transcricao = transcritor.transcrever(audio)
        else:
            # Vídeo sem áudio: transcrição vazia, para a análise não esperar por ela.
            transcricao = Transcricao(modelo=NOME_DO_MODELO, idioma=IDIOMA, palavras=[])
        armazenamento.gravar_transcricao(job_id, transcricao)
    except Exception:
        transitar(
            repositorio,
            job_id,
            "analisando",
            "falhou",
            agora(),
            codigo_falha="transcricao_falhou",
        )
        raise


def main() -> None:
    # O log do Job diz em qual dispositivo rodou (`api.whisper`, `api.paddle`, em INFO).
    log_estruturado.configurar(logging.WARNING)
    logging.getLogger("api").setLevel(logging.INFO)
    if teste_dos_jobs.ativo():
        # Teste depois da publicação (#238): amostra da imagem, nada no Storage nem no Firestore.
        raise SystemExit(teste_dos_jobs.testar_transcricao())
    projeto = os.environ["GCP_PROJECT_ID"]
    executar(
        os.environ["JOB_ID"],
        jobs_do_ambiente(firestore.Client(project=projeto)),
        TranscricoesStorage(
            ClienteStorage(project=projeto), os.environ["BUCKET_ACEITOS"]
        ),
        TranscritorFasterWhisper.da_pasta(os.environ["PASTA_DO_MODELO"]),
        Path(os.environ["TMPDIR"]),
    )


if __name__ == "__main__":
    main()
