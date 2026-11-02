"""Cloud Run Job da análise: manda o proxy ao Gemini, por janelas, e grava a decupagem.

O Workflows passa o id do Job em `JOB_ID`, depois do OCR da tela. Só um Job em
`analisando` é processado; qualquer outro estado (evento repetido, Job já concluído)
sai sem fazer nada. A falha da análise é tratada: o Job vai a `falhou` e a execução
termina bem, para o Workflows não tratá-la de novo. Rodar de novo o mesmo Job retoma
as janelas já concluídas (`api/progresso_das_janelas.py`).

É um Job, e não um serviço chamado por HTTP, porque a análise de um programa de
2–3 h passa do teto de 1800 s da chamada HTTP do Workflows (decisão registrada no #127).
"""

import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol, cast

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.analise_por_janelas import analisar_video
from api.catalogo import Catalogo
from api.ciclo_de_vida import transitar
from api.decupagem import Video
from api.gemini import AnaliseFalhou, SessaoHttp, Transporte, TransporteVertex
from api.identificacao import TOLERANCIA_DA_FALA_MS
from api.jobs import RepositorioDeJobs, agora_utc
from api.leitura_da_tela import LeituraDaTela
from api.nuvem import (
    CatalogoFirestore,
    DecupagensStorage,
    JanelasStorage,
    LeiturasStorage,
    RepositorioFirestore,
    TranscricoesStorage,
)
from api.progresso_das_janelas import JanelasDoJob
from api.sinais import (
    ContagemDaAnalise,
    Registrar,
    imprimir,
    registro_da_falha_de_etapa,
    registro_do_video_concluido,
)
from api.transcricao import Transcricao
from api.versao_pipeline import VERSAO_PIPELINE, manifesto


class DecupagensDaAnalise(Protocol):
    """Porta do Cloud Storage para a análise; os testes usam um dublê em memória."""

    def uri_do_proxy(self, job_id: str) -> str: ...

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None: ...


class TranscricoesDaAnalise(Protocol):
    """Porta para ler a transcrição que o Job de transcrição guardou."""

    def ler_transcricao(self, job_id: str) -> Transcricao | None: ...


class LeiturasDaAnalise(Protocol):
    """Porta para ler a leitura da tela que o Job de OCR guardou."""

    def ler_leitura(self, job_id: str) -> LeituraDaTela | None: ...


log = logging.getLogger(__name__)


def executar(
    job_id: str,
    repositorio: RepositorioDeJobs,
    decupagens: DecupagensDaAnalise,
    transporte: Transporte,
    transcricoes: TranscricoesDaAnalise | None = None,
    leituras: LeiturasDaAnalise | None = None,
    janelas_do_job: JanelasDoJob | None = None,
    max_paralelas: int = 1,
    catalogo: Catalogo | None = None,
    tolerancia_da_fala_ms: int = TOLERANCIA_DA_FALA_MS,
    dormir: Callable[[float], None] = time.sleep,
    relogio: Callable[[], datetime] = agora_utc,
    registrar: Registrar = imprimir,
) -> str:
    """Devolve `ignorado`, `concluido`, `falhou` ou `cancelado`."""
    job = repositorio.obter(job_id)
    if job is None or job.estado != "analisando":
        return "ignorado"

    def falhar(motivo: str) -> str:
        registrar(registro_da_falha_de_etapa("analise", job.id, motivo))
        falhou = transitar(
            repositorio,
            job.id,
            "analisando",
            "falhou",
            relogio(),
            codigo_falha="analise_falhou",
        )
        return "falhou" if falhou else "cancelado"

    if job.sha256 is None or job.duracao_s is None:
        return falhar("job sem sha256 ou duração")
    contagem = ContagemDaAnalise()
    try:
        decupagem = analisar_video(
            transporte,
            video_uri=decupagens.uri_do_proxy(job.id),
            job_id=job.id,
            programa=job.programa,
            cortes_ms=job.cortes_ms or (),
            video=Video(
                sha256=job.sha256,
                duracao_ms=round(job.duracao_s * 1000),
                timecode_origem=job.timecode_origem,
            ),
            transcricao=transcricoes.ler_transcricao(job.id) if transcricoes else None,
            leitura=leituras.ler_leitura(job.id) if leituras else None,
            max_paralelas=max_paralelas,
            janelas_do_job=janelas_do_job,
            catalogo=catalogo,
            tolerancia_da_fala_ms=tolerancia_da_fala_ms,
            dormir=dormir,
            contagem=contagem,
        )
    except AnaliseFalhou as e:
        return falhar(str(e) or "análise falhou")
    except Exception as e:
        # Erro que não é da resposta do modelo (um defeito na consolidação, por
        # exemplo): o traceback fica no log e o Job vai a `falhou` por aqui, sem
        # depender do `except` do Workflows.
        log.exception("análise do Job %s falhou com erro inesperado", job.id)
        return falhar(f"{type(e).__name__}: {e}")
    # A Decupagem só fica visível com o Job `concluido`: se o cancelamento
    # chegou antes da transição, o arquivo gravado aqui não é lido por ninguém.
    decupagem = decupagem.model_copy(
        update={
            "versao_pipeline": VERSAO_PIPELINE,
            "manifesto_do_pipeline": manifesto(),
        }
    )
    decupagens.gravar_decupagem(job.id, decupagem.model_dump_json())
    if transitar(repositorio, job.id, "analisando", "concluido", relogio()):
        registrar(
            registro_do_video_concluido(job.id, job.programa, decupagem, contagem)
        )
        return "concluido"
    return "cancelado"


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    aceitos = os.environ["BUCKET_ACEITOS"]
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = cast(SessaoHttp, AuthorizedSession(credenciais))  # type: ignore[no-untyped-call]
    executar(
        os.environ["JOB_ID"],
        RepositorioFirestore(firestore.Client(project=projeto)),
        DecupagensStorage(
            ClienteStorage(project=projeto), aceitos, os.environ["BUCKET_DECUPAGENS"]
        ),
        TransporteVertex(projeto, sessao, imprimir),
        TranscricoesStorage(ClienteStorage(project=projeto), aceitos),
        LeiturasStorage(ClienteStorage(project=projeto), aceitos),
        JanelasStorage(ClienteStorage(project=projeto), aceitos),
        max_paralelas=int(os.environ["JANELAS_EM_PARALELO"]),
        catalogo=CatalogoFirestore(firestore.Client(project=projeto)),
        tolerancia_da_fala_ms=int(
            os.environ.get("TOLERANCIA_DA_FALA_MS", TOLERANCIA_DA_FALA_MS)
        ),
    )


if __name__ == "__main__":
    main()
