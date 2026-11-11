"""Os quadros que o modelo forte olha: 2 ou 3 de cada pessoa, das aparições mais longas.

Os quadros saem da cópia limpa do vídeo, em resolução alta, por um passo sem
internet; o ffmpeg lê só arquivo (`-protocol_whitelist file`).
"""

import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from api.decupagem import _Intervalo
from api.quadros import FalhaNosQuadros

QUADROS_POR_PESSOA = 3
TEMPO_LIMITE_S = 120  # um quadro só, mesmo de um vídeo de 4 h (a busca é por chave)
# Instantes por processo do ffmpeg. Cada instante abre o arquivo de novo (um `-i` cada), com
# seu decodificador; 16 mantém a linha de comando curta e a memória em poucas centenas de MB
# num vídeo em alta resolução, e já dilui o início do processo.
INSTANTES_POR_PROCESSO = 16


def instantes_das_aparicoes(
    aparicoes: Sequence[_Intervalo], maximo: int = QUADROS_POR_PESSOA
) -> list[int]:
    """Instantes (ms) dos quadros: o meio de cada uma das `maximo` aparições mais
    longas. Com uma aparição só, dois quadros dela, a 1/3 e a 2/3. Em ordem de tempo.
    A mesma aparição repetida (duas entradas da mesma pessoa) conta uma vez."""
    unicas = {(a.inicio_ms, a.fim_ms): a for a in aparicoes}.values()
    mais_longas = sorted(unicas, key=lambda a: a.duracao_ms, reverse=True)[:maximo]
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


def extrair_quadros_em_lote(
    video: Path, instantes_ms: Sequence[int]
) -> list[bytes | None]:
    """Como `extrair_quadros`, mas vários instantes por processo do ffmpeg e sem erro por
    instante: o que não saiu (depois do fim, falha, timeout) vem `None`, depois de uma
    nova tentativa sozinho, que é o que `extrair_quadros` faria."""
    saida: list[bytes | None] = []
    for i in range(0, len(instantes_ms), INSTANTES_POR_PROCESSO):
        saida.extend(_lote(video, instantes_ms[i : i + INSTANTES_POR_PROCESSO]))
    return saida


def _lote(video: Path, instantes_ms: Sequence[int]) -> list[bytes | None]:
    if not instantes_ms:
        return []
    comando = ["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file"]
    for ms in instantes_ms:
        comando += ["-ss", f"{ms / 1000:.3f}", "-i", str(video)]
    with tempfile.TemporaryDirectory() as pasta:
        for n in range(len(instantes_ms)):
            comando += [
                "-an",
                "-map",
                f"{n}:v:0",
                "-frames:v",
                "1",
                "-vf",
                "format=yuvj420p",
                "-c:v",
                "mjpeg",
                "-q:v",
                "2",
                "-f",
                "image2",
                "-update",
                "1",
                f"{pasta}/{n}.jpg",
            ]
        try:
            ok = (
                subprocess.run(
                    comando,
                    check=False,
                    capture_output=True,
                    stdin=subprocess.DEVNULL,
                    timeout=TEMPO_LIMITE_S * len(instantes_ms),
                ).returncode
                == 0
            )
        except subprocess.TimeoutExpired:
            ok = False
        # Com erro ou timeout os arquivos podem estar pela metade: nada se aproveita.
        achados = [Path(f"{pasta}/{n}.jpg") for n in range(len(instantes_ms))]
        jpegs = [a.read_bytes() if ok and a.exists() else b"" for a in achados]
    resultado: list[bytes | None] = []
    for ms, jpeg in zip(instantes_ms, jpegs, strict=True):
        if jpeg:
            resultado.append(jpeg)
            continue
        try:
            resultado.append(_quadro(video, ms))
        except FalhaNosQuadros:
            resultado.append(None)
    return resultado


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
