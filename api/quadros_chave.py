"""Um JPEG por momento da Decupagem, tirado da cópia limpa depois da análise.

Um por plano (no meio dele), um por aparição (no meio dela) e um por objeto (no meio da
primeira ocorrência). O campo `quadro` do momento guarda o caminho do JPEG, relativo à
pasta do Job no bucket das decupagens. O Job roda sem internet, com o ffmpeg da imagem da
validação.
"""

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.decupagem import Decupagem
from api.jobs import RepositorioDeJobs
from api.nuvem import (
    QuadrosStorage,
    RepositorioFirestore,
)

TEMPO_LIMITE_S = 120


class FalhaNoQuadroChave(Exception):
    pass


def tirar_quadro(video: Path, instante_ms: int, destino: Path) -> bytes:
    """O JPEG do quadro do instante: o `-ss` antes do `-i` salta pelo índice do arquivo."""
    try:
        resultado = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file", "-y",
                "-ss", f"{instante_ms / 1000:.3f}", "-i", str(video),
                "-an", "-frames:v", "1", "-q:v", "3", str(destino),
            ],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=TEMPO_LIMITE_S,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise FalhaNoQuadroChave from None
    if resultado.returncode != 0 or not destino.is_file():
        raise FalhaNoQuadroChave
    return destino.read_bytes()


def com_quadros_chave(
    video: Path,
    decupagem: Decupagem,
    gravar: Callable[[str, bytes], None],
    pasta: Path,
) -> Decupagem:
    """A decupagem com `quadro` em cada plano, aparição e objeto.

    `gravar(caminho, jpeg)` guarda o JPEG. Os nomes saem da posição do momento, não do id
    que o modelo deu, que não é seguro como nome de objeto.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    pronta = decupagem.model_copy(deep=True)

    def quadro(nome: str, inicio_ms: int, fim_ms: int) -> str:
        caminho = f"quadros/{nome}.jpg"
        gravar(caminho, tirar_quadro(video, (inicio_ms + fim_ms) // 2, pasta / "q.jpg"))
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


def executar(
    job_id: str,
    repositorio: RepositorioDeJobs,
    armazenamento: QuadrosStorage,
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
        pasta / "quadros",
    )
    armazenamento.gravar_decupagem(job_id, pronta.model_dump_json())


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
