"""Cortes de câmera: o filtro `scene` do ffmpeg, com limiar configurável."""

import subprocess
from pathlib import Path

LIMIAR_PADRAO = 0.3
TEMPO_LIMITE_S = 7200


class DeteccaoFalhou(Exception):
    pass


def detectar_cortes(video: Path, limiar: float = LIMIAR_PADRAO) -> list[int]:
    """Os instantes dos cortes em ms, em ordem; vazio para um vídeo de um plano só."""
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file",
                "-i", str(video), "-an",
                "-vf", f"select='gt(scene,{limiar})',metadata=print:file=-",
                "-f", "null", "-",
            ],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=TEMPO_LIMITE_S,
            text=True,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise DeteccaoFalhou from None
    if r.returncode != 0:
        raise DeteccaoFalhou
    cortes: set[int] = set()
    for linha in r.stdout.splitlines():
        # "frame:0    pts:10240   pts_time:1"
        _, achou, resto = linha.partition("pts_time:")
        if achou:
            ms = round(float(resto.split()[0]) * 1000)
            if ms > 0:
                cortes.add(ms)
    return sorted(cortes)
