"""Adaptador do PaddleOCR: o único lugar que importa a biblioteca.

O grupo de dependências `ocr` não entra no `make verificar`; os testes passam um
modelo falso. Os modelos vêm da pasta da imagem, sem internet.
"""

from pathlib import Path
from typing import Any

from api.leitura_da_tela import Caixa, LinhaLida

NOME_DO_MODELO = "PP-OCRv5_server_det+latin_PP-OCRv5_mobile_rec"
DETECTOR = "PP-OCRv5_server_det"
RECONHECEDOR = "latin_PP-OCRv5_mobile_rec"


def _carregar(pasta_dos_modelos: str) -> Any:
    from paddleocr import PaddleOCR

    pasta = Path(pasta_dos_modelos)
    return PaddleOCR(
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
    def da_pasta(cls, pasta_dos_modelos: str) -> "LeitorPaddle":
        return cls(_carregar(pasta_dos_modelos))

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
