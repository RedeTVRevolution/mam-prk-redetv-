"""Cloud Run Job da comparação com as fotos de referência (#112), sem internet.

O Workflows passa `JOB_ID` depois das referências. O Job lê a Decupagem, compara as
pessoas sem nome confirmado com as fotos do bucket de referências (`comparar`) e
regrava a Decupagem; os vereditos vão para `<job_id>.comparacao.json`, para auditoria.
Como a identificação, é um aprimoramento: falha do modelo ou dos quadros deixa a
Decupagem como está e a execução termina bem.
"""

import json
import os
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol, cast

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.catalogo import Catalogo
from api.comparacao import (
    LIMIAR_PADRAO,
    LIMITE_DE_PESSOAS,
    Fotos,
    comparar,
)
from api.decupagem import Decupagem
from api.gemini import AnaliseFalhou, SessaoHttp, Transporte, TransporteVertex
from api.jobs import RepositorioDeJobs, agora_utc
from api.nuvem import (
    CatalogoFirestore,
    DecupagensStorage,
    ReferenciasStorage,
    RepositorioFirestore,
    SugestoesFirestore,
)
from api.quadros import FalhaNosQuadros
from api.quadros_das_pessoas import extrair_quadros
from api.referencias import Sugestoes, acervo_ligado

VALIDADE_PADRAO_DIAS = 180


class DecupagensDaComparacao(Protocol):
    def ler_decupagem(self, job_id: str) -> Decupagem | None: ...

    def baixar_copia_limpa(self, job_id: str, destino: Path) -> bool: ...

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None: ...

    def gravar_comparacao(self, job_id: str, conteudo: str) -> None: ...


def executar(
    job_id: str,
    repositorio: RepositorioDeJobs,
    decupagens: DecupagensDaComparacao,
    transporte: Transporte,
    fotos: Fotos,
    catalogo: Catalogo,
    sugestoes: Sugestoes,
    pasta: Path,
    *,
    validade: timedelta,
    com_acervo: bool = False,
    limiar: float = LIMIAR_PADRAO,
    limite_de_pessoas: int = LIMITE_DE_PESSOAS,
) -> str:
    """Devolve `ignorado`, `sem_alteracao` ou `comparado`."""
    job = repositorio.obter(job_id)
    if job is None or job.estado != "concluido":
        return "ignorado"
    decupagem = decupagens.ler_decupagem(job_id)
    copia = pasta / f"{job_id}.copia_limpa.mp4"
    if decupagem is None or not decupagens.baixar_copia_limpa(job_id, copia):
        return "sem_alteracao"
    try:
        resultado = comparar(
            decupagem,
            transporte=transporte,
            quadros_em=lambda instantes: extrair_quadros(copia, instantes),
            fotos=fotos,
            catalogo=catalogo,
            job_id=job_id,
            agora=agora_utc(),
            validade=validade,
            programa=job.programa,
            sugestoes=sugestoes,
            com_acervo=com_acervo,
            limiar=limiar,
            limite_de_pessoas=limite_de_pessoas,
        )
    except (AnaliseFalhou, FalhaNosQuadros):
        return "sem_alteracao"
    decupagens.gravar_decupagem(job_id, resultado.decupagem.model_dump_json())
    decupagens.gravar_comparacao(
        job_id,
        json.dumps([asdict(v) for v in resultado.vereditos], default=str),
    )
    return "comparado"


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = cast(SessaoHttp, AuthorizedSession(credenciais))  # type: ignore[no-untyped-call]
    executar(
        os.environ["JOB_ID"],
        RepositorioFirestore(firestore.Client(project=projeto)),
        DecupagensStorage(
            ClienteStorage(project=projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        TransporteVertex(projeto, sessao),
        ReferenciasStorage(
            ClienteStorage(project=projeto), os.environ["BUCKET_REFERENCIAS"]
        ),
        CatalogoFirestore(firestore.Client(project=projeto)),
        SugestoesFirestore(firestore.Client(project=projeto)),
        Path(os.environ["TMPDIR"]),
        validade=timedelta(
            days=int(
                os.environ.get("VALIDADE_DAS_REFERENCIAS_DIAS", VALIDADE_PADRAO_DIAS)
            )
        ),
        com_acervo=acervo_ligado(os.environ),
        limiar=float(os.environ.get("LIMIAR_DA_COMPARACAO", LIMIAR_PADRAO)),
        limite_de_pessoas=int(
            os.environ.get("LIMITE_DE_COMPARACOES", LIMITE_DE_PESSOAS)
        ),
    )


if __name__ == "__main__":
    main()
