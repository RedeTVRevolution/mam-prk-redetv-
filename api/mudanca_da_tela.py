"""Quando a imagem mudou o bastante para o OCR ler de novo (#233).

O OCR é o custo grande da leitura da tela (um quadro por segundo, ~1 h de CPU por hora de
vídeo). A maior parte dos quadros de 1 s é igual ao anterior na parte que tem texto: o
quadro que não mudou repete a leitura do último lido, e o resultado guardado segue com
um quadro por segundo.

A comparação é com o **último quadro lido**, não com o anterior: uma troca lenta (fade)
acumula até passar do limiar, em vez de passar sem ser lida. Cada quadro é reduzido a
`LARGURA x ALTURA` em tons de cinza (a média de cada bloco apaga o ruído da compressão e
o movimento pequeno) e cortado em `FAIXAS` faixas horizontais, cada uma em `COLUNAS`
blocos; muda se **algum** bloco tem diferença média absoluta (0 a 255) acima do limiar.
Por faixa, e não pela imagem inteira, porque o texto que entra (uma tarja no terço de
baixo, um GC) é pouca área da imagem e sumiria na média; e a faixa se mexe pouco num
plano com movimento de câmera ou de gente em outra parte da tela. Em blocos, e não pela
faixa inteira, porque a troca de um dígito do placar ou do relógio, ou do nome dentro de
uma tarja parada, mexe uns poucos pontos do quadro reduzido e também sumiria na média da
faixa.
"""

import math
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

LARGURA = 128
ALTURA = 72
FAIXAS = 6
COLUNAS = 8

# Palpite inicial (diferença média, em níveis de cinza, de um bloco): o ruído da
# compressão do proxy fica abaixo de 1, e uma linha de texto que entra muda o seu bloco em
# bem mais que isso. Quem acerta o valor é a medição no ar (#240), com `make comparar-leituras`.
LIMIAR_PADRAO = 3.0


def limiar_do_ambiente(ambiente: dict[str, str] | None = None) -> float:
    """`LIMIAR_DE_MUDANCA`; 0 lê todos os quadros, como antes."""
    valor = (os.environ if ambiente is None else ambiente).get("LIMIAR_DE_MUDANCA")
    if valor is None or not valor.strip():
        return LIMIAR_PADRAO
    limiar = float(valor)
    if not math.isfinite(limiar) or limiar < 0:
        raise ValueError(f"LIMIAR_DE_MUDANCA inválido: {valor!r} (zero ou mais)")
    return limiar


def _blocos(quadro: Path) -> list[Image.Image]:
    with Image.open(quadro) as imagem:
        reduzida = imagem.convert("L").resize((LARGURA, ALTURA), Image.Resampling.BOX)
    altura = ALTURA // FAIXAS
    largura = LARGURA // COLUNAS
    return [
        reduzida.crop((j * largura, i * altura, (j + 1) * largura, (i + 1) * altura))
        for i in range(FAIXAS)
        for j in range(COLUNAS)
    ]


class MudancaDaTela:
    """`mudou(quadro)` diz se o quadro pede nova leitura e, se pede, vira a referência."""

    def __init__(self, limiar: float) -> None:
        self.limiar = limiar
        self._lido: list[Image.Image] | None = None

    def mudou(self, quadro: Path) -> bool:
        if self.limiar <= 0:
            return True
        blocos = _blocos(quadro)
        if self._lido is not None and all(
            ImageStat.Stat(ImageChops.difference(antes, agora)).mean[0] <= self.limiar
            for antes, agora in zip(self._lido, blocos, strict=True)
        ):
            return False
        self._lido = blocos
        return True
