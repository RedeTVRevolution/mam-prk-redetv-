"""Cloud Run Job da identificação pelo modelo forte (#112), sem internet.

O Workflows passa `JOB_ID` depois da análise. O Job lê a Decupagem gravada, tira os
quadros das pessoas sem nome da `copia_limpa.mp4` (em resolução alta) e a regrava com os
nomes que o modelo forte deu e a identificação conferiu. Melhorar a Decupagem é opcional:
sem ela, sem a cópia limpa ou com uma falha do modelo, ela fica como está e a execução
termina bem, para o Workflows seguir.
"""

import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol, cast

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.catalogo import Catalogo
from api.ciclo_de_vida import rodar_etapa
from api.decupagem import Decupagem
from api.gemini import AnaliseFalhou, SessaoHttp, Transporte, TransporteVertex
from api.jobs import RepositorioDeJobs, agora_utc
from api.modelo_forte import LIMITE_DE_PESSOAS, olhar_pessoas_sem_nome
from api.nomes_a_buscar import nomes_a_buscar
from api.nuvem import (
    CatalogoFirestore,
    DecupagensStorage,
    RepositorioFirestore,
    TranscricoesStorage,
)
from api.quadros import FalhaNosQuadros
from api.quadros_das_pessoas import extrair_quadros
from api.transcricao import Transcricao

VALIDADE_PADRAO_DIAS = 180


class DecupagensDaIdentificacao(Protocol):
    def ler_decupagem(self, job_id: str) -> Decupagem | None: ...

    def baixar_copia_limpa(self, job_id: str, destino: Path) -> bool: ...

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None: ...

    def gravar_nomes_a_buscar(self, job_id: str, conteudo: str) -> None: ...


class TranscricoesDaIdentificacao(Protocol):
    def ler_transcricao(self, job_id: str) -> Transcricao | None: ...


def _deixar_os_nomes(
    job_id: str,
    decupagens: DecupagensDaIdentificacao,
    decupagem: Decupagem,
    programa: str | None,
    catalogo: Catalogo,
    validade: timedelta,
) -> None:
    """A lista de nomes que o Job de referências busca (#222)."""
    lista = nomes_a_buscar(decupagem, programa, catalogo, agora_utc(), validade)
    decupagens.gravar_nomes_a_buscar(job_id, lista.model_dump_json())


def executar(
    job_id: str,
    repositorio: RepositorioDeJobs,
    decupagens: DecupagensDaIdentificacao,
    transporte: Transporte,
    transcricoes: TranscricoesDaIdentificacao,
    catalogo: Catalogo,
    pasta: Path,
    *,
    limite_de_pessoas: int = LIMITE_DE_PESSOAS,
    validade: timedelta = timedelta(days=VALIDADE_PADRAO_DIAS),
) -> str:
    """Devolve `ignorado`, `sem_alteracao`, `incompleto` ou `identificado`.

    A etapa só conclui com `identificado`; `incompleto` é a falha do modelo ou dos quadros
    em alguma pessoa (as outras são gravadas) e `sem_alteracao`, a falta da Decupagem ou
    da cópia limpa. Nenhuma derruba o Job nem a execução."""
    job = repositorio.obter(job_id)
    if job is None or job.estado != "concluido":
        return "ignorado"

    def trabalho() -> str:
        decupagem = decupagens.ler_decupagem(job_id)
        copia = pasta / f"{job_id}.copia_limpa.mp4"
        if decupagem is None or not decupagens.baixar_copia_limpa(job_id, copia):
            return "sem_alteracao"
        falhas: list[Exception] = []
        try:
            nova = olhar_pessoas_sem_nome(
                decupagem,
                transporte=transporte,
                quadros_em=lambda instantes: extrair_quadros(copia, instantes),
                job_id=job_id,
                programa=job.programa,
                transcricao=transcricoes.ler_transcricao(job_id),
                catalogo=catalogo,
                limite_de_pessoas=limite_de_pessoas,
                ao_falhar=falhas.append,
            )
        except (AnaliseFalhou, FalhaNosQuadros):
            # Sem o modelo forte a Decupagem fica como está, mas os candidatos e os
            # palpites dela ainda precisam de fotos.
            _deixar_os_nomes(
                job_id, decupagens, decupagem, job.programa, catalogo, validade
            )
            return "sem_alteracao"
        decupagens.gravar_decupagem(job_id, nova.model_dump_json())
        _deixar_os_nomes(job_id, decupagens, nova, job.programa, catalogo, validade)
        return "incompleto" if falhas else "identificado"

    return rodar_etapa(
        repositorio, job_id, "identificacao", trabalho, bem_sucedido="identificado"
    )


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
        TransporteVertex(projeto, sessao),
        TranscricoesStorage(ClienteStorage(project=projeto), aceitos),
        CatalogoFirestore(firestore.Client(project=projeto)),
        Path(os.environ["TMPDIR"]),
        limite_de_pessoas=int(
            os.environ.get("LIMITE_DE_PESSOAS_DO_MODELO_FORTE", LIMITE_DE_PESSOAS)
        ),
        validade=timedelta(
            days=int(
                os.environ.get("VALIDADE_DAS_REFERENCIAS_DIAS", VALIDADE_PADRAO_DIAS)
            )
        ),
    )


if __name__ == "__main__":
    main()
