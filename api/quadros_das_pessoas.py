"""Os quadros que o modelo forte olha: 2 ou 3 de cada pessoa, das aparições mais longas.

Os quadros saem da cópia limpa do vídeo, em resolução alta, por um passo sem
internet; o ffmpeg lê só arquivo (`-protocol_whitelist file`).
"""

import subprocess
from collections.abc import Sequence
from pathlib import Path

from api.decupagem import _Intervalo
from api.quadros import FalhaNosQuadros

QUADROS_POR_PESSOA = 3
TEMPO_LIMITE_S = 120  # um quadro só, mesmo de um vídeo de 4 h (a busca é por chave)


def instantes_das_aparicoes(
    aparicoes: Sequence[_Intervalo], maximo: int = QUADROS_POR_PESSOA
) -> list[int]:
    """Instantes (ms) dos quadros: o meio de cada uma das `maximo` aparições mais
    longas. Com uma aparição só, dois quadros dela, a 1/3 e a 2/3. Em ordem de tempo."""
    mais_longas = sorted(aparicoes, key=lambda a: a.duracao_ms, reverse=True)[:maximo]
    if len(mais_longas) == 1:
        a = mais_longas[0]
        instantes = [
            a.inicio_ms + a.duracao_ms // 3,
            a.inicio_ms + 2 * a.duracao_ms // 3,
        ]
    else:
        instantes = [a.inicio_ms + a.duracao_ms // 2 for a in mais_longas]
    return sorted(dict.fromkeys(instantes))


def extrair_quadros(video: Path, instantes_ms: Sequence[int]) -> list[bytes]:
    """Um JPEG, na resolução do arquivo, de cada instante (ms)."""
    return [_quadro(video, ms) for ms in instantes_ms]


def _quadro(video: Path, instante_ms: int) -> bytes:
    try:
        resultado = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-protocol_whitelist",
                "file",
                "-ss",
                f"{instante_ms / 1000:.3f}",
                "-i",
                str(video),
                "-an",
                "-frames:v",
                "1",
                "-vf",
                "format=yuvj420p",
                "-c:v",
                "mjpeg",
                "-q:v",
                "2",
                "-f",
                "image2pipe",
                "pipe:1",
            ],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=TEMPO_LIMITE_S,
        )
    except subprocess.TimeoutExpired:
        raise FalhaNosQuadros from None
    if resultado.returncode != 0 or not resultado.stdout:
        raise FalhaNosQuadros
    return resultado.stdout
