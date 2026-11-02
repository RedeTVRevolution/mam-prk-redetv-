"""Adaptador do PaddleOCR: o único lugar que importa a biblioteca.

O grupo de dependências `ocr` não entra no `make verificar`; os testes passam um
modelo falso. Os modelos vêm da pasta da imagem, sem internet.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from api.dispositivo import Dispositivo, exigir_gpu, ler_dispositivo
from api.leitura_da_tela import Caixa, LinhaLida

log = logging.getLogger(__name__)

DETECTOR = "PP-OCRv5_server_det"
RECONHECEDOR = "latin_PP-OCRv5_mobile_rec"
NOME_DO_MODELO = f"{DETECTOR}+{RECONHECEDOR}"

DISPOSITIVOS = {"cpu": "cpu", "gpu": "gpu:0"}


def _gpus() -> int:
    import paddle

    if not paddle.device.is_compiled_with_cuda():
        return 0
    return int(paddle.device.cuda.device_count())


def _carregar(
    pasta_dos_modelos: str,
    dispositivo: Dispositivo = "cpu",
    gpus: Callable[[], int] | None = None,
) -> Any:
    from paddleocr import PaddleOCR

    if dispositivo == "gpu":
        exigir_gpu((gpus or _gpus)(), "o Paddle")
    log.info("Leitura da tela em %s", dispositivo)
    pasta = Path(pasta_dos_modelos)
    return PaddleOCR(
        device=DISPOSITIVOS[dispositivo],
        text_detection_model_name=DETECTOR,
        text_detection_model_dir=str(pasta / DETECTOR),
        text_recognition_model_name=RECONHECEDOR,
        text_recognition_model_dir=str(pasta / RECONHECEDOR),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def _dimensoes(quadro: Path) -> tuple[int, int]:
    import cv2

    imagem = cv2.imread(str(quadro))
    altura, largura = imagem.shape[:2]
    return largura, altura


class LeitorPaddle:
    def __init__(self, modelo: Any, dimensoes: Any = _dimensoes) -> None:
        self._modelo = modelo
        self._dimensoes = dimensoes

    @classmethod
    def da_pasta(
        cls,
        pasta_dos_modelos: str,
        dispositivo: Dispositivo | None = None,
        carregar: Callable[..., Any] = _carregar,
    ) -> "LeitorPaddle":
        """`dispositivo` vem da variável `DISPOSITIVO` (cpu, por padrão) se não for dado."""
        return cls(carregar(pasta_dos_modelos, dispositivo or ler_dispositivo()))

    def ler(self, quadro: Path) -> list[LinhaLida]:
        largura, altura = self._dimensoes(quadro)
        linhas: list[LinhaLida] = []
        for resultado in self._modelo.predict(str(quadro)):
            for texto, confianca, caixa in zip(
                resultado["rec_texts"],
                resultado["rec_scores"],
                resultado["rec_boxes"],
                strict=True,
            ):
                if not texto.strip():
                    continue
                x0, y0, x1, y1 = (float(v) for v in caixa)
                linhas.append(
                    LinhaLida(
                        texto=texto.strip(),
                        confianca=float(confianca),
                        caixa=Caixa(
                            x=x0 / largura,
                            y=y0 / altura,
                            largura=(x1 - x0) / largura,
                            altura=(y1 - y0) / altura,
                        ),
                    )
                )
        return linhas
