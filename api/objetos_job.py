"""Ponto de entrada do Cloud Run Job de objetos (Florence-2).

O Job lê a Decupagem do bucket das decupagens, passa cada JPEG de `plano.quadros` pelo
Florence-2 e grava o resultado bruto (objetos e regiões legendadas, com a versão do
modelo) ao lado dela. Roda sem internet: o modelo vem da imagem. Não escreve no
Firestore; o Workflows decide o que fazer se a execução falhar.
"""

import io
import logging
import os
import time
from collections.abc import Callable
from typing import Protocol

from google.cloud.storage import Client as ClienteStorage
from PIL import Image

from api import teste_dos_jobs
from api.decupagem import Decupagem
from api.florence import (
    NOME_DO_MODELO,
    Configuracao,
    DetectorFlorence,
    ObjetoDetectado,
    ObjetosDaDecupagem,
    QuadroDetectado,
    RegiaoLegendada,
    ler_configuracao,
)
from api.nuvem import ObjetosStorage

log = logging.getLogger(__name__)

LADO_DO_HASH = 8


Detectado = tuple[list[ObjetoDetectado], list[RegiaoLegendada]]


class DetectorDeObjetos(Protocol):
    def detectar_lote(self, imagens: list[Image.Image]) -> list[Detectado]: ...


class ArmazenamentoDosObjetos(Protocol):
    """Porta do bucket das decupagens."""

    def ler_decupagem(self, job_id: str) -> Decupagem | None: ...

    def ler_quadro(self, job_id: str, caminho: str) -> bytes: ...

    def gravar_resultado(
        self, job_id: str, resultado: ObjetosDaDecupagem, destino: str | None
    ) -> None: ...


class ObjetosEmMemoria:
    def __init__(self) -> None:
        self.decupagens: dict[str, Decupagem] = {}
        self.quadros: dict[tuple[str, str], bytes] = {}
        self.resultados: dict[tuple[str, str | None], ObjetosDaDecupagem] = {}

    def ler_decupagem(self, job_id: str) -> Decupagem | None:
        return self.decupagens.get(job_id)

    def ler_quadro(self, job_id: str, caminho: str) -> bytes:
        return self.quadros[(job_id, caminho)]

    def gravar_resultado(
        self, job_id: str, resultado: ObjetosDaDecupagem, destino: str | None
    ) -> None:
        self.resultados[(job_id, destino)] = resultado


def hash_do_quadro(imagem: Image.Image) -> int:
    """Hash de diferença (dHash) de 64 bits: muda pouco quando o quadro muda pouco."""
    cinza = imagem.convert("L").resize((LADO_DO_HASH + 1, LADO_DO_HASH))
    pixels = cinza.tobytes()
    bits = 0
    for linha in range(LADO_DO_HASH):
        for coluna in range(LADO_DO_HASH):
            a = pixels[linha * (LADO_DO_HASH + 1) + coluna]
            b = pixels[linha * (LADO_DO_HASH + 1) + coluna + 1]
            bits = (bits << 1) | int(a > b)
    return bits


def _progresso(feitos: int, total: int, ultimo: int, a_cada: int) -> int:
    if feitos == total or feitos // a_cada > ultimo // a_cada:
        log.info("Quadros: %d/%d", feitos, total)
        return feitos
    return ultimo


def executar(
    job_id: str,
    armazenamento: ArmazenamentoDosObjetos,
    detector: DetectorDeObjetos,
    destino: str | None = None,
    configuracao: Configuracao | None = None,
    relogio: Callable[[], float] = time.monotonic,
) -> None:
    """Com a configuração padrão, um quadro por vez e nenhum pulado, como antes. Em
    `destino` alternativo (a medição do #329) o resultado leva os segundos gastos."""
    configuracao = configuracao or Configuracao()
    decupagem = armazenamento.ler_decupagem(job_id)
    if decupagem is None:
        raise RuntimeError(
            f"Não há Decupagem do Job {job_id} no bucket das decupagens."
        )
    pedidos = [
        (indice, caminho)
        for indice, plano in enumerate(decupagem.planos)
        for caminho in plano.quadros
    ]
    if not pedidos:
        raise RuntimeError(f"A Decupagem do Job {job_id} não tem quadros nos planos.")
    inicio = relogio()
    detectados: dict[str, Detectado] = {}
    tamanhos: dict[str, tuple[int, int]] = {}
    iguais_a: dict[
        str, str
    ] = {}  # quadro repetido -> quadro do mesmo plano que o cobre
    mantidos: dict[int, list[tuple[int, str]]] = {}  # plano -> (hash, caminho)
    lote: list[tuple[str, Image.Image]] = []
    ultimo = 0

    def rodar_lote() -> None:
        resultados = detector.detectar_lote([imagem for _, imagem in lote])
        for (caminho, _), resultado in zip(lote, resultados, strict=True):
            detectados[caminho] = resultado
        lote.clear()

    for feitos, (indice, caminho) in enumerate(pedidos, start=1):
        with Image.open(io.BytesIO(armazenamento.ler_quadro(job_id, caminho))) as foto:
            imagem = foto.convert("RGB")
        tamanhos[caminho] = imagem.size
        cobre = None
        if configuracao.pular_repetidos:
            impressao = hash_do_quadro(imagem)
            cobre = next(
                (
                    c
                    for h, c in mantidos.get(indice, [])
                    if (h ^ impressao).bit_count() <= configuracao.pular_repetidos
                ),
                None,
            )
            if cobre is None:
                mantidos.setdefault(indice, []).append((impressao, caminho))
        if cobre is not None:
            iguais_a[caminho] = cobre
        else:
            lote.append((caminho, imagem))
            if len(lote) >= configuracao.lote:
                rodar_lote()
        ultimo = _progresso(feitos, len(pedidos), ultimo, configuracao.log_a_cada)
    if lote:
        rodar_lote()
    quadros = []
    for indice, caminho in pedidos:
        objetos, regioes = detectados[iguais_a.get(caminho, caminho)]
        largura, altura = tamanhos[caminho]
        quadros.append(
            QuadroDetectado(
                plano=indice,
                caminho=caminho,
                largura=largura,
                altura=altura,
                objetos=objetos,
                regioes=regioes,
            )
        )
    armazenamento.gravar_resultado(
        job_id,
        ObjetosDaDecupagem(
            modelo=NOME_DO_MODELO,
            quadros=quadros,
            segundos=round(relogio() - inicio, 2) if destino else None,
        ),
        destino,
    )


def main() -> None:
    # O log do Job diz em qual dispositivo rodou (`api.florence`, em INFO).
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("api").setLevel(logging.INFO)
    if teste_dos_jobs.ativo():
        # Teste depois da publicação (#238): amostra da imagem, nada no Storage.
        raise SystemExit(teste_dos_jobs.testar_objetos())
    projeto = os.environ["GCP_PROJECT_ID"]
    configuracao = ler_configuracao()
    executar(
        os.environ["JOB_ID"],
        ObjetosStorage(
            ClienteStorage(project=projeto), os.environ["BUCKET_DECUPAGENS"]
        ),
        DetectorFlorence.da_pasta(
            os.environ["PASTA_DO_MODELO"], configuracao=configuracao
        ),
        os.environ.get("DESTINO_DO_RESULTADO") or None,
        configuracao,
    )


if __name__ == "__main__":
    main()
