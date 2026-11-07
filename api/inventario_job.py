"""Cloud Run Job em CPU do inventário de objetos (#244).

O Workflows passa `JOB_ID` depois dos quadros-chave. Com o motor `florence` (padrão), o
Job lê o resultado bruto do Job com GPU e o converte para o português numa chamada só de
texto ao Gemini; com o motor `gemini`, o modelo olha os quadros-chave. Em qualquer caso
o Job grava a Decupagem com o inventário de cada plano. O motor e o modelo vêm do
ambiente (`MOTOR_OBJETOS`, `MODELO_OBJETOS`). Uma falha sobe: o Workflows marca a etapa
como `falhou` e a indexação roda mesmo assim, sem inventário.
"""

import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud.storage import Client as ClienteStorage

from api import log_estruturado
from api.decupagem import Decupagem
from api.florence import ObjetosDaDecupagem
from api.gemini import SessaoHttp, Transporte, TransporteVertex
from api.inventario import (
    Inventarios,
    aplicar_inventario,
    converter_do_florence,
    olhar_com_gemini,
)
from api.nuvem import ObjetosStorage
from api.sinais import imprimir

MOTORES = ("florence", "gemini")


@dataclass(frozen=True)
class ConfigDoInventario:
    motor: Literal["florence", "gemini"]
    modelo: str
    # O bruto do Florence-2 num objeto à parte (a comparação dos motores, #243).
    destino_do_bruto: str | None = None


class ArmazenamentoDoInventario(Protocol):
    def ler_decupagem(self, job_id: str) -> Decupagem | None: ...

    def ler_resultado(
        self, job_id: str, destino: str | None = None
    ) -> ObjetosDaDecupagem | None: ...

    def ler_quadro(self, job_id: str, caminho: str) -> bytes: ...

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None: ...


def config_do_ambiente(ambiente: Mapping[str, str]) -> ConfigDoInventario:
    motor = ambiente.get("MOTOR_OBJETOS") or "florence"
    if motor not in MOTORES:
        raise ValueError(f"motor de objetos desconhecido: {motor!r}")
    return ConfigDoInventario(
        motor=cast(Literal["florence", "gemini"], motor),
        modelo=ambiente["MODELO_OBJETOS"],
        destino_do_bruto=ambiente.get("DESTINO_DO_RESULTADO") or None,
    )


def executar(
    job_id: str,
    armazenamento: ArmazenamentoDoInventario,
    transporte: Transporte,
    config: ConfigDoInventario,
    *,
    dormir: Callable[[float], None] = time.sleep,
) -> None:
    decupagem = armazenamento.ler_decupagem(job_id)
    if decupagem is None:
        raise RuntimeError(
            f"Não há Decupagem do Job {job_id} no bucket das decupagens."
        )
    inventarios: Inventarios
    if config.motor == "florence":
        bruto = armazenamento.ler_resultado(job_id, config.destino_do_bruto)
        if bruto is None:
            raise RuntimeError(
                f"O Job de objetos não gravou o resultado do Florence-2 do Job {job_id}."
            )
        inventarios = converter_do_florence(
            decupagem,
            bruto,
            transporte=transporte,
            modelo=config.modelo,
            job_id=job_id,
            dormir=dormir,
        )
    else:
        inventarios = olhar_com_gemini(
            decupagem,
            transporte=transporte,
            modelo=config.modelo,
            job_id=job_id,
            quadro_de=lambda caminho: armazenamento.ler_quadro(job_id, caminho),
            dormir=dormir,
        )
    nova = aplicar_inventario(
        decupagem, inventarios, motor=config.motor, modelo=config.modelo
    )
    armazenamento.gravar_decupagem(job_id, nova.model_dump_json())


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = cast(SessaoHttp, AuthorizedSession(credenciais))  # type: ignore[no-untyped-call]
    executar(
        os.environ["JOB_ID"],
        ObjetosStorage(
            ClienteStorage(project=projeto), os.environ["BUCKET_DECUPAGENS"]
        ),
        TransporteVertex(projeto, sessao, imprimir),
        config_do_ambiente(os.environ),
    )


if __name__ == "__main__":
    # Sem isto o Python cai no manejador padrão, em texto puro (#475).
    log_estruturado.configurar(logging.WARNING)
    main()
