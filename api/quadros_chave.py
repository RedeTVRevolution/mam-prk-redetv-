"""Um JPEG por momento da Decupagem, tirado da cópia limpa depois da análise.

Um a três por plano (conforme a duração), um por aparição (no meio dela) e um por objeto
(no meio da primeira ocorrência); o alvo escuro desvia para um instante próximo e claro.
O campo `quadro` do momento guarda o caminho do JPEG, relativo à pasta do Job no bucket
das decupagens; o plano guarda também todos em `quadros`. O Job roda sem internet, com o
ffmpeg da imagem da validação, e tira cada quadro como os do modelo forte
(`extrair_quadros`).
"""

import io
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from google.cloud.storage import Client as ClienteStorage
from PIL import Image, ImageStat

from api import log_estruturado
from api.bancos import cliente_do_firestore
from api.decupagem import Decupagem, caminho_do_quadro
from api.jobs import RepositorioDeJobs
from api.nuvem import QuadrosStorage, RepositorioFirestore
from api.quadros import FalhaNosQuadros
from api.quadros_das_pessoas import extrair_quadros

# ponytail: limiar fixo, calibrar com os quadros do piloto
LIMIAR_DE_ESCURO = 20  # luminância média, de 0 a 255
DESVIOS_MS = (1_000, -1_000, 2_000, -2_000, 3_000, -3_000)
FOLGA_DAS_BORDAS_MS = 500


def instantes_alvo(inicio_ms: int, fim_ms: int) -> list[int]:
    """Os instantes (ms) dos quadros de um plano: 1 abaixo de 10 s, 2 até 30 s, 3 depois."""
    duracao = fim_ms - inicio_ms
    if duracao < 10_000:
        fracoes = [(1, 2)]
    elif duracao < 30_000:
        fracoes = [(1, 3), (2, 3)]
    else:
        fracoes = [(1, 4), (2, 4), (3, 4)]
    return [inicio_ms + duracao * n // d for n, d in fracoes]


def e_escuro(jpeg: bytes) -> bool:
    with Image.open(io.BytesIO(jpeg)) as imagem:
        return ImageStat.Stat(imagem.convert("L")).mean[0] < LIMIAR_DE_ESCURO


class QuadrosDoJob(Protocol):
    """Porta do Cloud Storage para os quadros-chave; os testes usam um dublê."""

    def baixar_copia_limpa(self, job_id: str, destino: Path) -> bool: ...

    def ler_decupagem(self, job_id: str) -> Decupagem | None: ...

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
    # Instante (ms) -> (o JPEG, se é escuro). O resultado só depende do instante, e o meio de
    # uma aparição ou objeto cai muitas vezes no de um plano; o `e_escuro` decodifica o JPEG
    # inteiro, então também fica guardado. Só os acertos entram: a falha (timeout passageiro,
    # ffmpeg que saiu com erro) é tentada de novo pelo próximo momento no mesmo instante.
    # ponytail: nunca é esvaziado; um vídeo tem poucos milhares de instantes.
    cache: dict[int, tuple[bytes, bool]] = {}

    def jpeg_em(instante: int) -> tuple[bytes, bool] | None:
        if instante not in cache:
            try:
                [jpeg] = extrair_quadros(video, [instante])
            except FalhaNosQuadros:
                return None
            cache[instante] = (jpeg, e_escuro(jpeg))
        return cache[instante]

    def claro(alvo_ms: int, inicio_ms: int, fim_ms: int) -> tuple[int, bytes] | None:
        """O primeiro quadro não escuro: o alvo, depois ±1 s, ±2 s e ±3 s dele."""
        for desvio in (0, *DESVIOS_MS):
            instante = alvo_ms + desvio
            if desvio and not (
                inicio_ms + FOLGA_DAS_BORDAS_MS
                <= instante
                <= fim_ms - FOLGA_DAS_BORDAS_MS
            ):
                continue
            achado = jpeg_em(instante)
            if achado is not None and not achado[1]:
                return instante, achado[0]
        return None

    def quadro(nome: str, inicio_ms: int, fim_ms: int) -> str | None:
        achado = claro((inicio_ms + fim_ms) // 2, inicio_ms, fim_ms)
        if achado is None:
            return None
        caminho = caminho_do_quadro(f"{nome}.jpg")
        gravar(caminho, achado[1])
        return caminho

    for i, plano in enumerate(pronta.planos):
        achados: dict[int, bytes] = {}
        for alvo in instantes_alvo(plano.inicio_ms, plano.fim_ms):
            achado = claro(alvo, plano.inicio_ms, plano.fim_ms)
            if achado is not None:
                achados.setdefault(*achado)
        meio = (plano.inicio_ms + plano.fim_ms) / 2
        representativo = min(achados, key=lambda t: abs(t - meio), default=None)
        plano.quadro = None
        plano.quadros = []
        outros = 0
        for instante in sorted(achados):
            if instante == representativo:
                arquivo = f"plano-{i}.jpg"
            else:
                arquivo = f"plano-{i}-{outros}.jpg"
                outros += 1
            caminho = caminho_do_quadro(arquivo)
            gravar(caminho, achados[instante])
            plano.quadros.append(caminho)
            if instante == representativo:
                plano.quadro = caminho
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
    decupagem = armazenamento.ler_decupagem(job_id)
    if decupagem is None or not armazenamento.baixar_copia_limpa(job_id, copia):
        raise FalhaNosQuadros(f"sem Decupagem ou cópia limpa do job {job_id}")
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
        RepositorioFirestore(cliente_do_firestore(projeto)),
        QuadrosStorage(
            ClienteStorage(project=projeto),
            os.environ["BUCKET_ACEITOS"],
            os.environ["BUCKET_DECUPAGENS"],
        ),
        Path(os.environ["TMPDIR"]),
    )


if __name__ == "__main__":
    # Sem isto o Python cai no manejador padrão, em texto puro (#475).
    log_estruturado.configurar(logging.WARNING)
    main()
