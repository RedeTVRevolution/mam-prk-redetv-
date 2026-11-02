"""Ponto de entrada do Cloud Run Job de objetos (Florence-2).

O Job lê a Decupagem do bucket das decupagens, passa cada JPEG de `plano.quadros` pelo
Florence-2 e grava o resultado bruto (objetos e regiões legendadas, com a versão do
modelo) ao lado dela. Roda sem internet: o modelo vem da imagem. Não escreve no
Firestore; o Workflows decide o que fazer se a execução falhar.
"""

import io
import logging
import os
from typing import Protocol

from google.cloud.storage import Client as ClienteStorage
from PIL import Image

from api import teste_dos_jobs
from api.decupagem import Decupagem
from api.florence import (
    NOME_DO_MODELO,
    DetectorFlorence,
    ObjetoDetectado,
    ObjetosDaDecupagem,
    QuadroDetectado,
    RegiaoLegendada,
)
from api.nuvem import ObjetosStorage


class DetectorDeObjetos(Protocol):
    def detectar(
        self, imagem: Image.Image
    ) -> tuple[list[ObjetoDetectado], list[RegiaoLegendada]]: ...


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


def executar(
    job_id: str,
    armazenamento: ArmazenamentoDosObjetos,
    detector: DetectorDeObjetos,
    destino: str | None = None,
) -> None:
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
    quadros: list[QuadroDetectado] = []
    for indice, caminho in pedidos:
        with Image.open(io.BytesIO(armazenamento.ler_quadro(job_id, caminho))) as foto:
            imagem = foto.convert("RGB")
        objetos, regioes = detector.detectar(imagem)
        quadros.append(
            QuadroDetectado(
                plano=indice,
                caminho=caminho,
                largura=imagem.width,
                altura=imagem.height,
                objetos=objetos,
                regioes=regioes,
            )
        )
    armazenamento.gravar_resultado(
        job_id, ObjetosDaDecupagem(modelo=NOME_DO_MODELO, quadros=quadros), destino
    )


def main() -> None:
    # O log do Job diz em qual dispositivo rodou (`api.florence`, em INFO).
    logging.basicConfig(format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("api").setLevel(logging.INFO)
    if teste_dos_jobs.ativo():
        # Teste depois da publicação (#238): amostra da imagem, nada no Storage.
        raise SystemExit(teste_dos_jobs.testar_objetos())
    projeto = os.environ["GCP_PROJECT_ID"]
    executar(
        os.environ["JOB_ID"],
        ObjetosStorage(
            ClienteStorage(project=projeto), os.environ["BUCKET_DECUPAGENS"]
        ),
        DetectorFlorence.da_pasta(os.environ["PASTA_DO_MODELO"]),
        os.environ.get("DESTINO_DO_RESULTADO") or None,
    )


if __name__ == "__main__":
    main()
