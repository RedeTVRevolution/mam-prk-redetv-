"""Cortes de câmera: o filtro `scene` do ffmpeg, com limiar configurável."""

import subprocess
from pathlib import Path
from typing import Literal

LIMIAR_PADRAO = 0.3
# Também o tempo de cada chamada ao ffmpeg/ffprobe do validador (`api/validador.py`).
TEMPO_LIMITE_S = 7200
TAMANHO_DO_STDERR = 300

CausaDaFalha = Literal["tempo_esgotado", "ffmpeg_saiu_com_erro"]


def resumir_stderr(bruto: bytes | str | None) -> str:
    """O fim do stderr da ferramenta (onde ela diz o erro), curto: só para o log."""
    if isinstance(bruto, bytes):
        bruto = bruto.decode(errors="replace")
    return (bruto or "").strip()[-TAMANHO_DO_STDERR:]


class DeteccaoFalhou(Exception):
    """A causa e o stderr resumido (que só vai para o log) vão na mensagem."""

    def __init__(self, causa: CausaDaFalha, stderr: str = "") -> None:
        super().__init__(f"{causa}: {stderr}" if stderr else causa)
        self.causa = causa
        self.stderr = stderr


def filtro_de_cortes(limiar: float) -> str:
    """O filtro `scene` que imprime o `pts_time` de cada corte no stdout do ffmpeg."""
    return f"select='gt(scene,{limiar})',metadata=print:file=-"


def ler_cortes(saida_do_filtro: str) -> list[int]:
    """Os instantes dos cortes em ms, em ordem, lidos do `metadata=print` do filtro."""
    cortes: set[int] = set()
    for linha in saida_do_filtro.splitlines():
        # "frame:0    pts:10240   pts_time:1"
        _, achou, resto = linha.partition("pts_time:")
        if achou:
            ms = round(float(resto.split()[0]) * 1000)
            if ms > 0:
                cortes.add(ms)
    return sorted(cortes)


def detectar_cortes(video: Path, limiar: float = LIMIAR_PADRAO) -> list[int]:
    """Os instantes dos cortes em ms, em ordem; vazio para um vídeo de um plano só."""
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file",
                "-i", str(video), "-an",
                "-vf", filtro_de_cortes(limiar),
                "-f", "null", "-",
            ],
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=TEMPO_LIMITE_S,
            text=True,
        )  # fmt: skip
    except subprocess.TimeoutExpired as e:
        raise DeteccaoFalhou("tempo_esgotado", resumir_stderr(e.stderr)) from e
    if r.returncode != 0:
        raise DeteccaoFalhou("ffmpeg_saiu_com_erro", resumir_stderr(r.stderr))
    return ler_cortes(r.stdout)
