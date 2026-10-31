"""Detecção de cortes de câmera num vídeo sintético de cortes conhecidos."""

import shutil
import subprocess
from pathlib import Path

import pytest

from api.cortes import LIMIAR_PADRAO, detectar_cortes

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")

QUADRO_MS = 100  # 10 quadros por segundo


def _concatenar(destino: Path, cores: list[tuple[str, float]]) -> Path:
    entradas: list[str] = []
    for cor, duracao in cores:
        entradas += ["-f", "lavfi", "-i", f"color={cor}:s=160x120:r=10:d={duracao}"]
    ligacao = "".join(f"[{i}]" for i in range(len(cores)))
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", *entradas,
            "-filter_complex", f"{ligacao}concat=n={len(cores)}:v=1:a=0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(destino),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return destino


def test_cortes_saem_a_ate_um_quadro_do_esperado(tmp_path: Path) -> None:
    video = _concatenar(
        tmp_path / "v.mp4", [("red", 2.0), ("blue", 1.5), ("green", 2.5), ("white", 1)]
    )
    cortes = detectar_cortes(video, LIMIAR_PADRAO)
    esperados = [2_000, 3_500, 6_000]
    assert len(cortes) == len(esperados)
    for achado, esperado in zip(cortes, esperados, strict=True):
        assert abs(achado - esperado) <= QUADRO_MS


def test_video_de_um_plano_so_nao_tem_cortes(tmp_path: Path) -> None:
    video = _concatenar(tmp_path / "v.mp4", [("red", 3.0)])
    assert detectar_cortes(video, LIMIAR_PADRAO) == []


def test_limiar_alto_demais_nao_acha_corte(tmp_path: Path) -> None:
    video = _concatenar(tmp_path / "v.mp4", [("red", 2.0), ("blue", 2.0)])
    assert detectar_cortes(video, 0.99) == []
