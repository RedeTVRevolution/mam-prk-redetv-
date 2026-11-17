"""Cloud Run Job da identificação pelo modelo forte (#112), sem internet.

O Workflows passa `JOB_ID` depois da análise. O Job lê a Decupagem gravada, tira os
quadros das pessoas sem nome da `copia_limpa.mp4` (em resolução alta) e a regrava com os
nomes que o modelo forte deu e a identificação conferiu. Melhorar a Decupagem é opcional:
sem ela, sem a cópia limpa ou com uma falha do modelo, ela fica como está e a execução
termina bem, para o Workflows seguir.
"""

import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from google.cloud.storage import Client as ClienteStorage

from api import log_estruturado
from api.ambiente import FaltaNoAmbiente
from api.bancos import cliente_do_firestore
from api.catalogo import Catalogo
from api.ciclo_de_vida import rodar_etapa
from api.clientes_de_nuvem import sessao_autenticada
from api.correcoes import Correcao
from api.decupagem import Decupagem
from api.gemini import Transporte, TransporteVertex
from api.identificacao import TOLERANCIA_DA_FALA_MS, tolerancia_da_fala_do_ambiente
from api.juncao_de_pessoas import juntar_sem_nome
from api.modelo_do_job import RepositorioDeJobs
from api.modelo_forte import LIMITE_DE_PESSOAS, grupos_a_olhar, olhar_pessoas_sem_nome
from api.nuvem import (
    CatalogoFirestore,
    DecupagensStorage,
    ProgramasFirestore,
    RepositorioDeCorrecoesFirestore,
    RepositorioFirestore,
    TranscricoesStorage,
)
from api.programas import Perfis, perfis_dos_programas
from api.quadros_das_pessoas import extrair_quadros
from api.regras_das_correcoes import pares_proibidos, pessoas_corrigidas
from api.sinais import imprimir
from api.transcricao import Transcricao


class DecupagensDaIdentificacao(Protocol):
    def ler_decupagem(self, job_id: str) -> Decupagem | None: ...

    def baixar_copia_limpa(self, job_id: str, destino: Path) -> bool: ...

    def copia_limpa_existe(self, job_id: str) -> bool: ...

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None: ...


class CorrecoesDaIdentificacao(Protocol):
    def listar(self, job_id: str) -> list[Correcao]: ...


class TranscricoesDaIdentificacao(Protocol):
    def ler_transcricao(self, job_id: str) -> Transcricao | None: ...


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
    tolerancia_ms: int = TOLERANCIA_DA_FALA_MS,
    perfis: Perfis | None = None,
    correcoes: CorrecoesDaIdentificacao | None = None,
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
        if decupagem is None:
            return "sem_alteracao"
        # Decide antes de baixar: sem pessoa sem nome a olhar, a cópia limpa só precisa
        # existir (`identificado` é o que conclui a etapa; sem a cópia, ela falha).
        if grupos_a_olhar(decupagem, limite_de_pessoas):
            if not decupagens.baixar_copia_limpa(job_id, copia):
                return "sem_alteracao"
        elif not decupagens.copia_limpa_existe(job_id):
            return "sem_alteracao"
        falhas: list[Exception] = []

        def quadros_em(instantes: Sequence[int]) -> list[bytes]:
            return extrair_quadros(copia, instantes)

        nova = olhar_pessoas_sem_nome(
            decupagem,
            transporte=transporte,
            quadros_em=quadros_em,
            job_id=job_id,
            programa=job.programa,
            perfis=perfis,
            transcricao=transcricoes.ler_transcricao(job_id),
            catalogo=catalogo,
            limite_de_pessoas=limite_de_pessoas,
            tolerancia_ms=tolerancia_ms,
            ao_falhar=falhas.append,
        )
        # A junção das pessoas sem nome é o último passo, depois do modelo forte: assim
        # uma pessoa nomeada por ele nunca absorve outra e o nome nunca se espalha. As
        # separações que uma pessoa fez na tela ainda valem num reprocessamento (#547).
        # Sem juiz do modelo: ele acertou 3 de 6 no dev (#547); a faixa ambígua não junta.
        feitas = correcoes.listar(job_id) if correcoes else []
        nova = juntar_sem_nome(
            nova,
            proibidos=pares_proibidos(feitas),
            corrigidas=pessoas_corrigidas(feitas),
        )
        decupagens.gravar_decupagem(job_id, nova.model_dump_json())
        return "incompleto" if falhas else "identificado"

    return rodar_etapa(
        repositorio, job_id, "identificacao", trabalho, bem_sucedido="identificado"
    )


def main() -> None:
    try:
        decupagens = DecupagensStorage.do_ambiente()
    except FaltaNoAmbiente as e:
        print(f"erro: {e}", file=sys.stderr)
        sys.exit(2)
    projeto = os.environ["GCP_PROJECT_ID"]
    aceitos = os.environ["BUCKET_ACEITOS"]
    sessao = sessao_autenticada()
    catalogo = CatalogoFirestore(cliente_do_firestore(projeto))
    executar(
        os.environ["JOB_ID"],
        RepositorioFirestore(cliente_do_firestore(projeto)),
        decupagens,
        TransporteVertex(projeto, sessao, imprimir),
        TranscricoesStorage(ClienteStorage(project=projeto), aceitos),
        catalogo,
        Path(os.environ["TMPDIR"]),
        correcoes=RepositorioDeCorrecoesFirestore(cliente_do_firestore(projeto)),
        perfis=perfis_dos_programas(
            ProgramasFirestore(cliente_do_firestore(projeto)), catalogo
        ),
        limite_de_pessoas=int(
            os.environ.get("LIMITE_DE_PESSOAS_DO_MODELO_FORTE", LIMITE_DE_PESSOAS)
        ),
        tolerancia_ms=tolerancia_da_fala_do_ambiente(),
    )


if __name__ == "__main__":
    # Sem isto o Python cai no manejador padrão, em texto puro (#475).
    log_estruturado.configurar(logging.WARNING)
    main()
