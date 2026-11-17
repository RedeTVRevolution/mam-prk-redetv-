"""Vídeo 4:3 e anamórfico (SAR diferente de 1:1): proxy e quadros saem com pixel quadrado."""

import json
import subprocess
from pathlib import Path

import pytest

from api.quadros import tirar_quadros
from api.quadros_das_pessoas import extrair_quadros, extrair_quadros_em_lote
from api.validador import validar


def _gerar(destino: Path, tamanho: str, sar: str | None) -> Path:
    filtro = f"testsrc2=s={tamanho}:r=10:d=2" + (f",setsar={sar}" if sar else "")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", filtro,
         "-f", "lavfi", "-i", "sine=d=2", "-c:v", "libx264", "-c:a", "aac", str(destino)],
        check=True, capture_output=True,
    )  # fmt: skip
    return destino


def _dimensoes(arquivo: Path) -> tuple[int, int, str]:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,sample_aspect_ratio", "-of", "json", str(arquivo)],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    v = json.loads(saida)["streams"][0]
    return v["width"], v["height"], v.get("sample_aspect_ratio", "N/A")


# (tamanho de armazenamento, SAR, largura esperada do proxy a 480 de altura)
CASOS = [
    ("720x480", "8/9", 640),  # NTSC 4:3
    ("720x480", "10/11", 654),  # NTSC 4:3 (ITU-R 601: 720*10/11 = 654,5)
    ("720x576", "16/15", 640),  # PAL 4:3 (768x576 na altura original)
    ("720x480", "32/27", 854),  # NTSC 16:9 anamórfico
    ("640x480", "1/1", 640),
    ("854x480", "1/1", 854),
    ("1280x720", "1/1", 854),
    ("640x480", None, 640),
]


@pytest.mark.parametrize(("tamanho", "sar", "largura"), CASOS)
def test_proxy_sai_com_pixel_quadrado_e_a_largura_do_aspecto_de_exibicao(
    tmp_path: Path, tamanho: str, sar: str | None, largura: int
) -> None:
    entrada = _gerar(tmp_path / "v.mp4", tamanho, sar)

    aceito = validar(entrada, tmp_path / "saida")

    l, a, sar_saida = _dimensoes(aceito.proxy)
    assert (l, a) == (largura, 480)
    assert sar_saida in ("1:1", "N/A")


def test_quadros_do_proxy_herdam_o_pixel_quadrado(tmp_path: Path) -> None:
    aceito = validar(_gerar(tmp_path / "v.mp4", "720x480", "8/9"), tmp_path / "saida")

    quadros = tirar_quadros(aceito.proxy, tmp_path / "q")

    assert quadros
    assert _dimensoes(quadros[0])[:2] == (640, 480)


@pytest.mark.parametrize(("tamanho", "sar", "largura"), CASOS)
def test_jpeg_da_copia_limpa_sai_com_pixel_quadrado(
    tmp_path: Path,
    tamanho: str,
    sar: str | None,
    largura: int,  # noqa: ARG001
) -> None:
    altura = int(tamanho.split("x")[1])
    entrada = _gerar(tmp_path / "v.mp4", tamanho, sar)
    # A largura de exibição na altura original: a mesma conta do proxy, sem reduzir.
    num, den = map(int, (sar or "1/1").split("/"))
    esperada = round(int(tamanho.split("x")[0]) * num / den / 2) * 2

    for jpegs in (
        extrair_quadros(entrada, [500]),
        extrair_quadros_em_lote(entrada, [500, 1000]),
    ):
        for n, jpeg in enumerate(jpegs):
            assert jpeg
            arq = tmp_path / f"q{n}.jpg"
            arq.write_bytes(jpeg)
            assert _dimensoes(arq)[:2] == (esperada, altura)
