"""Um JPEG por momento da Decupagem, tirado da cópia limpa depois da análise.

Um por plano (no meio dele), um por aparição (no meio dela) e um por objeto (no meio da
primeira ocorrência). O campo `quadro` do momento guarda o caminho do JPEG, relativo à
pasta do Job no bucket das decupagens. O Job roda sem internet, com o ffmpeg da imagem da
validação, e tira cada quadro como os do modelo forte (`extrair_quadros`).
"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.decupagem import Decupagem, caminho_do_quadro
from api.jobs import RepositorioDeJobs
from api.nuvem import QuadrosStorage, RepositorioFirestore
from api.quadros import FalhaNosQuadros
from api.quadros_das_pessoas import extrair_quadros


class QuadrosDoJob(Protocol):
    """Porta do Cloud Storage para os quadros-chave; os testes usam um dublê."""

    def baixar_copia_limpa(self, job_id: str, destino: Path) -> None: ...

    def ler_decupagem(self, job_id: str) -> bytes: ...

    def gravar_quadro(self, job_id: str, caminho: str, jpeg: bytes) -> None: ...

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None: ...


def com_quadros_chave(
    video: Path, decupagem: Decupagem, gravar: Callable[[str, bytes], None]
) -> Decupagem:
    """A decupagem com `quadro` em cada plano, aparição e objeto.

    `gravar(caminho, jpeg)` guarda o JPEG. Os nomes saem da posição do momento, não do id
    que o modelo deu, que não é seguro como nome de objeto. O momento cujo quadro o
    ffmpeg não tira (um instante depois do fim do vídeo) fica sem `quadro`; os outros não
    se perdem por ele.
    """
    pronta = decupagem.model_copy(deep=True)

    def quadro(nome: str, inicio_ms: int, fim_ms: int) -> str | None:
        try:
            [jpeg] = extrair_quadros(video, [(inicio_ms + fim_ms) // 2])
        except FalhaNosQuadros:
            return None
        caminho = caminho_do_quadro(f"{nome}.jpg")
        gravar(caminho, jpeg)
        return caminho

    for i, plano in enumerate(pronta.planos):
        plano.quadro = quadro(f"plano-{i}", plano.inicio_ms, plano.fim_ms)
    for i, pessoa in enumerate(pronta.pessoas):
        for j, aparicao in enumerate(pessoa.na_imagem):
            aparicao.quadro = quadro(
                f"aparicao-{i}-{j}", aparicao.inicio_ms, aparicao.fim_ms
            )
    for i, objeto in enumerate(pronta.objetos):
        primeira = min(objeto.ocorrencias, key=lambda o: o.inicio_ms)
        objeto.quadro = quadro(f"objeto-{i}", primeira.inicio_ms, primeira.fim_ms)
    return pronta


def capa_da_decupagem(decupagem: Decupagem) -> str | None:
    """O quadro de capa: o do primeiro plano com pessoa na imagem, ou o do primeiro plano.

    Só entram planos que ganharam quadro; sem nenhum, não há capa.
    """
    planos = sorted(
        (p for p in decupagem.planos if p.quadro is not None),
        key=lambda p: p.inicio_ms,
    )
    aparicoes = [a for pessoa in decupagem.pessoas for a in pessoa.na_imagem]
    for plano in planos:
        if any(
            a.inicio_ms < plano.fim_ms and a.fim_ms > plano.inicio_ms for a in aparicoes
        ):
            return plano.quadro
    return planos[0].quadro if planos else None


def executar(
    job_id: str,
    repositorio: RepositorioDeJobs,
    armazenamento: QuadrosDoJob,
    pasta: Path,
) -> None:
    job = repositorio.obter(job_id)
    if job is None or job.estado != "concluido":
        return
    copia = pasta / f"{job_id}.mp4"
    armazenamento.baixar_copia_limpa(job_id, copia)
    decupagem = Decupagem.model_validate_json(armazenamento.ler_decupagem(job_id))
    pronta = com_quadros_chave(
        copia,
        decupagem,
        lambda caminho, jpeg: armazenamento.gravar_quadro(job_id, caminho, jpeg),
    )
    armazenamento.gravar_decupagem(job_id, pronta.model_dump_json())
    # Grava também a falta de capa: um reprocessamento sem quadros não deixa a antiga.
    repositorio.transitar(job_id, "concluido", {"capa": capa_da_decupagem(pronta)})


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    executar(
        os.environ["JOB_ID"],
        RepositorioFirestore(firestore.Client(project=projeto)),
        QuadrosStorage(
            ClienteStorage(project=projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        Path(os.environ["TMPDIR"]),
    )


if __name__ == "__main__":
    main()
