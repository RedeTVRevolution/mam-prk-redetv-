"""Quadros por segundo, Job de OCR, adaptador do PaddleOCR e a porta da leitura, sem modelo real."""

import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from api.jobs import Estado, Job, RepositorioEmMemoria
from api.leitura_da_tela import (
    Caixa,
    LeituraDaTela,
    LeiturasEmMemoria,
    LinhaLida,
    QuadroLido,
)
from api.ocr_job import executar
from api.paddle import DETECTOR, RECONHECEDOR, LeitorPaddle
from api.quadros import FalhaNosQuadros, tirar_quadros

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
sem_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


def _video(destino: Path, segundos: float) -> bytes:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={segundos}:size=160x120:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(destino),
        ],
        check=True,
    )
    return destino.read_bytes()


def _linha(texto: str) -> LinhaLida:
    return LinhaLida(
        texto=texto,
        confianca=0.9,
        caixa=Caixa(x=0.1, y=0.2, largura=0.5, altura=0.1),
    )


class LeitorFalso:
    def __init__(self, erro: Exception | None = None) -> None:
        self.erro = erro
        self.quadros: list[Path] = []

    def ler(self, quadro: Path) -> list[LinhaLida]:
        self.quadros.append(quadro)
        if self.erro:
            raise self.erro
        return [_linha(f"quadro {len(self.quadros) - 1}")]


def _repositorio(estado: Estado = "analisando") -> RepositorioEmMemoria:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(
        Job(
            id="j1",
            nome="j1.mp4",
            tamanho_bytes=1,
            estado=estado,
            criado_por="uid-1",
            criado_em=BASE,
            atualizado_em=BASE,
        )
    )
    return repositorio


@sem_ffmpeg
def test_um_quadro_por_segundo_do_video_sintetico(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    _video(video, 3.4)

    quadros = tirar_quadros(video, tmp_path / "q")

    assert [q.name for q in quadros] == [
        "quadro_00001.png",
        "quadro_00002.png",
        "quadro_00003.png",
        "quadro_00004.png",
    ]


@sem_ffmpeg
def test_o_quadro_do_segundo_e_o_do_instante_exato(tmp_path: Path) -> None:
    # 10 quadros por segundo, e o brilho de cada um é 7 vezes o número do quadro.
    video = tmp_path / "v.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=16x16:r=10,format=gray,geq=lum='N*7'",
            "-t",
            "3.4",
            "-c:v",
            "libx264",
            "-qp",
            "0",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )

    quadros = tirar_quadros(video, tmp_path / "q")

    brilhos = [
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(q),
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "-",
            ],
            check=True,
            capture_output=True,
        ).stdout[100]
        for q in quadros
    ]
    assert [round(b / 7) for b in brilhos] == [0, 10, 20, 30]


@sem_ffmpeg
def test_video_ilegivel_nao_gera_quadros(tmp_path: Path) -> None:
    lixo = tmp_path / "v.mp4"
    lixo.write_bytes(b"nao e um video")

    with pytest.raises(FalhaNosQuadros):
        tirar_quadros(lixo, tmp_path / "q")


@sem_ffmpeg
def test_job_le_cada_quadro_e_grava_o_resultado_por_segundo(tmp_path: Path) -> None:
    repositorio = _repositorio()
    porta = LeiturasEmMemoria({"j1": _video(tmp_path / "origem.mp4", 3.4)})
    leitor = LeitorFalso()
    pasta = tmp_path / "saida"
    pasta.mkdir()

    executar("j1", repositorio, porta, leitor, pasta)

    assert [q.name for q in leitor.quadros] == [
        "quadro_00001.png",
        "quadro_00002.png",
        "quadro_00003.png",
        "quadro_00004.png",
    ]
    leitura = porta.ler_leitura("j1")
    assert leitura is not None
    assert [(q.segundo, q.linhas[0].texto) for q in leitura.quadros] == [
        (0, "quadro 0"),
        (1, "quadro 1"),
        (2, "quadro 2"),
        (3, "quadro 3"),
    ]
    assert repositorio.obter("j1").estado == "analisando"  # type: ignore[union-attr]


def test_leitura_com_posicao_das_linhas_e_gravada_e_lida_pela_porta() -> None:
    porta = LeiturasEmMemoria()
    leitura = LeituraDaTela(
        modelo="falso",
        quadros=[
            QuadroLido(segundo=0, linhas=[_linha("DIA DO MEDICAMENTO BARATO")]),
            QuadroLido(segundo=1, linhas=[]),
        ],
    )

    assert porta.ler_leitura("j1") is None
    porta.gravar_leitura("j1", leitura)

    lida = porta.ler_leitura("j1")
    assert lida == leitura
    assert lida.quadros[0].linhas[0].caixa.largura == 0.5


@sem_ffmpeg
def test_falha_do_ocr_derruba_o_job_com_codigo_proprio(tmp_path: Path) -> None:
    repositorio = _repositorio()
    porta = LeiturasEmMemoria({"j1": _video(tmp_path / "origem.mp4", 2)})
    pasta = tmp_path / "saida"
    pasta.mkdir()

    with pytest.raises(RuntimeError):
        executar("j1", repositorio, porta, LeitorFalso(RuntimeError("x")), pasta)

    job = repositorio.obter("j1")
    assert job is not None
    assert (job.estado, job.codigo_falha) == ("falhou", "ocr_falhou")
    assert porta.ler_leitura("j1") is None


@sem_ffmpeg
def test_proxy_que_nao_e_video_derruba_o_job(tmp_path: Path) -> None:
    repositorio = _repositorio()
    porta = LeiturasEmMemoria({"j1": b"lixo"})

    with pytest.raises(FalhaNosQuadros):
        executar("j1", repositorio, porta, LeitorFalso(), tmp_path)

    assert repositorio.obter("j1").codigo_falha == "ocr_falhou"  # type: ignore[union-attr]


@pytest.mark.parametrize("estado", ["cancelado", "concluido", "validando"])
def test_job_fora_de_analisando_nao_le(estado: Estado, tmp_path: Path) -> None:
    leitor = LeitorFalso()

    executar(
        "j1",
        _repositorio(estado),
        LeiturasEmMemoria({"j1": b"x"}),
        leitor,
        tmp_path,
    )

    assert leitor.quadros == []


def test_job_inexistente_nao_faz_nada(tmp_path: Path) -> None:
    leitor = LeitorFalso()

    executar("nenhum", RepositorioEmMemoria(), LeiturasEmMemoria(), leitor, tmp_path)

    assert leitor.quadros == []


class ModeloFalso:
    def predict(self, quadro: str) -> list[dict[str, Any]]:
        return [
            {
                "rec_texts": ["  ULTRAFARMA.COM ", "  "],
                "rec_scores": [0.97, 0.3],
                "rec_boxes": [[16, 12, 96, 36], [0, 0, 1, 1]],
            }
        ]


def test_adaptador_normaliza_a_caixa_e_descarta_linha_vazia(tmp_path: Path) -> None:
    leitor = LeitorPaddle(ModeloFalso(), dimensoes=lambda _: (160, 120))

    (linha,) = leitor.ler(tmp_path / "q.png")

    assert linha.texto == "ULTRAFARMA.COM"
    assert linha.confianca == pytest.approx(0.97)
    assert linha.caixa == Caixa(x=0.1, y=0.1, largura=0.5, altura=0.2)


def test_modelos_do_dockerfile_estao_fixados_por_revisao_e_hash() -> None:
    dockerfile = (Path(__file__).parents[2] / "Dockerfile").read_text()
    alvo = dockerfile[dockerfile.index("AS ocr") :].split("\nFROM ")[0]

    for nome in ("DETECTOR", "RECONHECEDOR"):
        assert re.search(rf"^ARG {nome}_REVISAO=[0-9a-f]{{40}}$", alvo, re.MULTILINE)
        assert re.search(rf"^ARG {nome}_SHA256=[0-9a-f]{{64}}$", alvo, re.MULTILINE)
    assert "sha256sum -c" in alvo
    assert "--group ocr" in alvo
    assert "ffmpeg=$FFMPEG" in alvo
    assert f"ARG DETECTOR={DETECTOR}\n" in alvo
    assert f"ARG RECONHECEDOR={RECONHECEDOR}\n" in alvo


def test_versao_do_ffmpeg_vale_para_todos_os_estagios() -> None:
    # Um ARG depois de um FROM só vale naquele estágio; o `ARG FFMPEG` dos alvos chegaria vazio.
    dockerfile = (Path(__file__).parents[2] / "Dockerfile").read_text()

    assert dockerfile.index("\nARG FFMPEG=") < dockerfile.index("\nFROM ")
