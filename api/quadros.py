"""Um quadro por segundo do proxy, tirado pelo ffmpeg."""

import subprocess
from pathlib import Path

TEMPO_LIMITE_S = 900
PADRAO = "quadro_%05d.png"


class FalhaNosQuadros(Exception):
    pass


def tirar_quadros(video: Path, pasta: Path) -> list[Path]:
    """Os quadros de 0 s, 1 s, 2 s…, em ordem: o do índice `i` é o do segundo `i`."""
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        resultado = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-protocol_whitelist",
                "file",
                "-y",
                "-i",
                str(video),
                "-an",
                "-vf",
                "fps=1",
                str(pasta / PADRAO),
            ],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=TEMPO_LIMITE_S,
        )
    except subprocess.TimeoutExpired:
        raise FalhaNosQuadros from None
    if resultado.returncode != 0:
        raise FalhaNosQuadros
    return sorted(pasta.glob("quadro_*.png"))
