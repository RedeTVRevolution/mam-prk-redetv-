"""Quadros-chave dos momentos (#115): um JPEG por plano, aparição e objeto."""

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from api.decupagem import Decupagem
from api.jobs import Job, RepositorioEmMemoria
from api.quadros_chave import com_quadros_chave, executar

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")

COR_DO_PLANO = [("red", 2.0), ("blue", 2.0), ("green", 2.0)]


def _video(destino: Path) -> Path:
    entradas: list[str] = []
    for cor, duracao in COR_DO_PLANO:
        entradas += ["-f", "lavfi", "-i", f"color={cor}:s=160x120:r=10:d={duracao}"]
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", *entradas,
            "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(destino),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return destino


def _decupagem() -> Decupagem:
    def plano(i: int, inicio: int, fim: int) -> dict[str, object]:
        return {
            "id": f"pla{i}",
            "inicio_ms": inicio,
            "fim_ms": fim,
            "ambiente": "estúdio",
            "plano_limpo": True,
        }

    return Decupagem.model_validate(
        {
            "versao_esquema": "1.3",
            "video": {"sha256": "a" * 64, "duracao_ms": 6_000},
            "programa": {"resumo": "r", "blocos": []},
            "pautas": [],
            "pessoas": [
                {
                    "id": "pes01",
                    "nome": "Fulana",
                    "na_imagem": [
                        {"inicio_ms": 0, "fim_ms": 1_000, "evidencia": "rosto"},
                        {"inicio_ms": 2_200, "fim_ms": 3_800, "evidencia": "rosto"},
                    ],
                    "citada_na_fala": [],
                    "citada_no_texto": [],
                }
            ],
            "objetos": [
                {
                    "id": "obj01",
                    "categoria": "calcado",
                    "tipo": "sandália",
                    "cor_base": ["vermelho"],
                    "ocorrencias": [
                        {"inicio_ms": 4_400, "fim_ms": 5_600},
                        {"inicio_ms": 0, "fim_ms": 1_000},
                    ],
                }
            ],
            "planos": [
                plano(0, 0, 2_000),
                plano(1, 2_000, 4_000),
                plano(2, 4_000, 6_000),
            ],
            "comerciais": [],
            "transcricao": [],
        }
    )


def _cor_media(jpeg: bytes, destino: Path) -> tuple[int, int, int]:
    arquivo = destino / "q.jpg"
    arquivo.write_bytes(jpeg)
    bruto = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(arquivo), "-vf", "scale=1:1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    return bruto[0], bruto[1], bruto[2]


def test_cada_plano_aparicao_e_objeto_tem_um_jpeg_e_o_quadro_aponta_para_ele(
    tmp_path: Path,
) -> None:
    gravados: dict[str, bytes] = {}

    pronta = com_quadros_chave(
        _video(tmp_path / "v.mp4"), _decupagem(), gravados.__setitem__
    )

    quadros = [
        *(p.quadro for p in pronta.planos),
        *(a.quadro for p in pronta.pessoas for a in p.na_imagem),
        *(o.quadro for o in pronta.objetos),
    ]
    assert all(q is not None for q in quadros)
    assert len(set(quadros)) == len(quadros) == 6
    assert set(quadros) == set(gravados)
    assert all(j.startswith(b"\xff\xd8") for j in gravados.values())


def test_o_quadro_e_do_meio_do_plano_e_da_primeira_ocorrencia_do_objeto(
    tmp_path: Path,
) -> None:
    gravados: dict[str, bytes] = {}

    pronta = com_quadros_chave(
        _video(tmp_path / "v.mp4"), _decupagem(), gravados.__setitem__
    )

    def cor(caminho: str | None) -> tuple[int, int, int]:
        assert caminho is not None
        return _cor_media(gravados[caminho], tmp_path)

    vermelho, azul, verde = (cor(p.quadro) for p in pronta.planos)
    assert vermelho[0] > 150 > vermelho[2]
    assert azul[2] > 150 > azul[0]
    assert verde[1] > 100 > verde[0]
    # A primeira ocorrência do objeto é a de 0 s (vermelho), não a primeira da lista (verde).
    assert cor(pronta.objetos[0].quadro)[0] > 150
    # A segunda aparição, no meio do plano azul.
    assert cor(pronta.pessoas[0].na_imagem[1].quadro)[2] > 150


def test_momento_depois_do_fim_do_video_fica_sem_quadro_e_os_outros_ficam(
    tmp_path: Path,
) -> None:
    decupagem = _decupagem()
    decupagem.planos[2].inicio_ms, decupagem.planos[2].fim_ms = 8_000, 9_000
    gravados: dict[str, bytes] = {}

    pronta = com_quadros_chave(
        _video(tmp_path / "v.mp4"), decupagem, gravados.__setitem__
    )

    assert pronta.planos[2].quadro is None
    assert pronta.planos[0].quadro in gravados
    assert pronta.planos[1].quadro in gravados
    assert len(gravados) == 5


class QuadrosFalso:
    def __init__(self, video: Path, decupagem: Decupagem) -> None:
        self.video = video
        self.decupagem = decupagem.model_dump_json()
        self.quadros: dict[str, bytes] = {}

    def baixar_copia_limpa(self, job_id: str, destino: Path) -> None:
        shutil.copy(self.video, destino)

    def ler_decupagem(self, job_id: str) -> bytes:
        return self.decupagem.encode()

    def gravar_quadro(self, job_id: str, caminho: str, jpeg: bytes) -> None:
        self.quadros[f"{job_id}/{caminho}"] = jpeg

    def gravar_decupagem(self, job_id: str, conteudo: str) -> None:
        self.decupagem = conteudo


def _job(repositorio: RepositorioEmMemoria, estado: Any) -> None:
    agora = datetime(2026, 10, 31, tzinfo=UTC)
    repositorio.salvar(
        Job(
            id="j1", nome="a.mp4", tamanho_bytes=1, estado=estado,
            criado_por="u", criado_em=agora, atualizado_em=agora,
        )
    )  # fmt: skip


def test_o_job_grava_os_jpegs_e_a_decupagem_com_o_caminho_de_cada_um(
    tmp_path: Path,
) -> None:
    repositorio = RepositorioEmMemoria()
    _job(repositorio, "concluido")
    armazenamento = QuadrosFalso(_video(tmp_path / "v.mp4"), _decupagem())
    (tmp_path / "saida").mkdir()

    executar("j1", repositorio, armazenamento, tmp_path / "saida")

    gravada = Decupagem.model_validate_json(armazenamento.decupagem)
    assert gravada.planos[0].quadro == "quadros/plano-0.jpg"
    assert set(armazenamento.quadros) == {
        "j1/quadros/plano-0.jpg",
        "j1/quadros/plano-1.jpg",
        "j1/quadros/plano-2.jpg",
        "j1/quadros/aparicao-0-0.jpg",
        "j1/quadros/aparicao-0-1.jpg",
        "j1/quadros/objeto-0.jpg",
    }


def test_job_que_nao_concluiu_nao_ganha_quadros(tmp_path: Path) -> None:
    repositorio = RepositorioEmMemoria()
    _job(repositorio, "cancelado")
    armazenamento = QuadrosFalso(_video(tmp_path / "v.mp4"), _decupagem())

    executar("j1", repositorio, armazenamento, tmp_path / "saida")

    assert armazenamento.quadros == {}
    assert (
        Decupagem.model_validate_json(armazenamento.decupagem).planos[0].quadro is None
    )
