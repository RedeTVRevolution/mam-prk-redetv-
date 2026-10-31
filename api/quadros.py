"""Um quadro por segundo do proxy, tirado pelo ffmpeg."""

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

# Um trecho de 600 quadros: no ffmpeg de um trecho, o tempo é o do trecho, não o do programa
# (medido: 120 s de 854x480 em 2 s; um trecho de 600 s leva ~10 s, com 1800 s de folga).
TEMPO_LIMITE_S = 1800
TRECHO_S = 600
PADRAO = "quadro_%05d.png"


class FalhaNosQuadros(Exception):
    pass


def tirar_quadros(
    video: Path, pasta: Path, inicio_s: int = 0, duracao_s: int | None = None
) -> list[Path]:
    """Os quadros de 0 s, 1 s, 2 s…, em ordem: o do índice `i` é o do segundo `i`.

    Com `inicio_s` e `duracao_s`, só os do trecho: o do índice `i` é o do segundo
    `inicio_s + i`; um trecho depois do fim não tem quadros.

    O `round=up` pega o quadro do instante exato de cada segundo; o padrão do `fps`
    (`near`) pegaria o de perto do meio do segundo.
    """
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
                *(["-ss", str(inicio_s)] if inicio_s else []),
                *(["-t", str(duracao_s)] if duracao_s is not None else []),
                "-i",
                str(video),
                "-an",
                "-vf",
                "fps=1:round=up",
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


def quadros_por_trecho(
    video: Path, pasta: Path, trecho_s: int = TRECHO_S
) -> Iterator[tuple[int, list[Path]]]:
    """`(segundo do primeiro quadro, quadros)` de `trecho_s` em `trecho_s` segundos.

    Os quadros do trecho anterior são apagados antes de tirar os do próximo: no volume
    há no máximo um trecho. O último trecho é o que vem com menos de `trecho_s` quadros.
    """
    inicio = 0
    while True:
        shutil.rmtree(pasta, ignore_errors=True)
        quadros = tirar_quadros(video, pasta, inicio, trecho_s)
        if quadros:
            yield inicio, quadros
        if len(quadros) < trecho_s:
            shutil.rmtree(pasta, ignore_errors=True)
            return
        inicio += trecho_s
