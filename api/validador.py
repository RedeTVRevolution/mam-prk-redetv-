"""Validador da quarentena: camadas 4 a 7 de Entradas hostis.

Devolve a cópia limpa, o proxy de reprodução e o SHA-256, ou levanta `Recusa`
com um código. A saída das ferramentas nunca sai daqui.
"""

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.jobs import CodigoDeFalha

MARCAS_PERMITIDAS = {b"isom", b"mp41", b"mp42", b"avc1"}
CODECS_VIDEO = {"h264", "hevc"}
LADO_CURTO_MAXIMO = 1080  # 1080p, também em retrato
LADO_LONGO_MAXIMO = 1920
DURACAO_MINIMA_S = 1.0
DURACAO_MAXIMA_S = 600.0
TEMPO_LIMITE_S = 900


class Recusa(Exception):
    def __init__(self, codigo: CodigoDeFalha) -> None:
        super().__init__(codigo)
        self.codigo = codigo


@dataclass(frozen=True)
class Aceito:
    copia_limpa: Path
    proxy: Path
    sha256: str
    duracao_s: float


def _executar(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=TEMPO_LIMITE_S,
        )
    except subprocess.TimeoutExpired:
        raise Recusa("arquivo_corrompido") from None


def _sha256(arquivo: Path) -> str:
    resumo = hashlib.sha256()
    with arquivo.open("rb") as f:
        while leitura := f.read(1 << 20):
            resumo.update(leitura)
    return resumo.hexdigest()


def _conferir_ftyp(entrada: Path) -> None:
    with entrada.open("rb") as f:
        cabecalho = f.read(12)
    if (
        len(cabecalho) < 12
        or cabecalho[4:8] != b"ftyp"
        or cabecalho[8:12] not in MARCAS_PERMITIDAS
    ):
        raise Recusa("formato_invalido")


def _sondar(entrada: Path) -> dict[str, Any]:
    # Só o leitor de MP4 e só arquivo local: nada de protocolos de rede.
    resultado = _executar(
        [
            "ffprobe", "-v", "error",
            "-protocol_whitelist", "file",
            "-f", "mov,mp4,m4a,3gp,3g2,mj2",
            "-show_streams", "-show_format", "-of", "json",
            str(entrada),
        ]
    )  # fmt: skip
    if resultado.returncode != 0:
        raise Recusa("arquivo_corrompido")
    try:
        sondagem: dict[str, Any] = json.loads(resultado.stdout)
    except ValueError:
        raise Recusa("arquivo_corrompido") from None
    return sondagem


def _duracao(sondagem: dict[str, Any]) -> float:
    try:
        return float(sondagem["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        raise Recusa("arquivo_corrompido") from None


def _conferir_faixas(sondagem: dict[str, Any]) -> None:
    faixas = sondagem.get("streams", [])
    videos = [f for f in faixas if f.get("codec_type") == "video"]
    audios = [f for f in faixas if f.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) > 1 or len(videos) + len(audios) != len(faixas):
        raise Recusa("codec_nao_suportado")
    if videos[0].get("codec_name") not in CODECS_VIDEO:
        raise Recusa("codec_nao_suportado")
    try:
        lados = sorted((int(videos[0]["width"]), int(videos[0]["height"])))
    except (KeyError, ValueError, TypeError):
        raise Recusa("arquivo_corrompido") from None
    if lados[0] > LADO_CURTO_MAXIMO or lados[1] > LADO_LONGO_MAXIMO:
        raise Recusa("codec_nao_suportado")
    if audios and audios[0].get("codec_name") != "aac":
        raise Recusa("codec_nao_suportado")


def validar(entrada: Path, saida: Path) -> Aceito:
    _conferir_ftyp(entrada)
    sondagem = _sondar(entrada)
    _conferir_faixas(sondagem)
    duracao = _duracao(sondagem)
    if not DURACAO_MINIMA_S <= duracao <= DURACAO_MAXIMA_S:
        raise Recusa("duracao_excedida")

    saida.mkdir(parents=True, exist_ok=True)
    copia = saida / "copia_limpa.mp4"
    proxy = saida / "proxy.mp4"
    comum = ["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file", "-y"]
    # Regravação sem recodificar: só vídeo e áudio, sem metadados nem capítulos.
    regravar = _executar(
        [
            *comum, "-i", str(entrada),
            "-map", "0:v", "-map", "0:a?",
            "-c", "copy", "-map_metadata", "-1", "-map_chapters", "-1",
            "-movflags", "+faststart", str(copia),
        ]
    )  # fmt: skip
    # Decodifica o arquivo inteiro e gera o proxy na mesma passada.
    gerar_proxy = _executar(
        [
            *comum, "-xerror", "-err_detect", "explode", "-i", str(entrada),
            "-map", "0:v", "-map", "0:a?",
            # veryfast: no clipe2, 41% mais rápido que o medium e SSIM de 0,986 contra 0,990.
            "-vf", "scale=-2:480", "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-map_metadata", "-1", "-map_chapters", "-1",
            "-movflags", "+faststart", str(proxy),
        ]
    )  # fmt: skip
    if regravar.returncode != 0 or gerar_proxy.returncode != 0:
        copia.unlink(missing_ok=True)
        proxy.unlink(missing_ok=True)
        raise Recusa("arquivo_corrompido")
    return Aceito(copia, proxy, _sha256(entrada), duracao)
