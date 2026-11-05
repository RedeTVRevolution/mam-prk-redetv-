"""Cada imagem com GPU leva só os módulos de `api/` que o ponto de entrada importa (#388)."""

import ast
import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[2]
API = RAIZ / "api"
ALVOS = {
    "transcricao-gpu": "transcricao_job",
    "ocr-gpu": "ocr_job",
    "objetos-gpu": "objetos_job",
}


def _importados(modulo: str) -> set[str]:
    """Os módulos de `api/` que o arquivo importa, também os importados dentro de funções."""
    achados: set[str] = set()
    for no in ast.walk(ast.parse((API / f"{modulo}.py").read_text())):
        if isinstance(no, ast.Import):
            achados |= {
                a.name.split(".")[1] for a in no.names if a.name.startswith("api.")
            }
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            if no.module == "api":
                achados |= {a.name for a in no.names}
            elif no.module.startswith("api."):
                achados.add(no.module.split(".")[1])
        elif isinstance(no, ast.ImportFrom) and no.level == 1:
            achados |= (
                {no.module.split(".")[0]} if no.module else {a.name for a in no.names}
            )
    return achados


def _fecho(entrada: str) -> set[str]:
    vistos: set[str] = set()
    pendentes = [entrada, "__init__"]
    while pendentes:
        modulo = pendentes.pop()
        if modulo not in vistos:
            vistos.add(modulo)
            pendentes += _importados(modulo)
    return vistos


def _arquivos_esperados(entrada: str) -> set[str]:
    modulos = _fecho(entrada)
    # Os arquivos de dados de `api/` (não só `.toml`) que algum módulo do fecho cita pelo nome.
    textos = [(API / f"{m}.py").read_text() for m in modulos]
    dados = {
        f"api/{arquivo.name}"
        for arquivo in API.iterdir()
        if arquivo.is_file() and arquivo.suffix not in {".py", ".pyc"}
        if any(f'"{arquivo.name}"' in texto for texto in textos)
    }
    return {f"api/{m}.py" for m in modulos} | dados


def _alvo(nome: str) -> str:
    dockerfile = (RAIZ / "Dockerfile").read_text()
    return dockerfile[dockerfile.index(f"AS {nome}\n") :].split("\nFROM ")[0]


def _copiados(alvo: str) -> set[str]:
    texto = alvo.replace("\\\n", " ")
    arquivos: set[str] = set()
    for linha in re.findall(r"^COPY (api/\S.*) api/$", texto, flags=re.MULTILINE):
        arquivos |= set(linha.split())
    return arquivos


@pytest.mark.parametrize(("alvo", "entrada"), ALVOS.items())
def test_imagens_gpu_copiam_so_o_que_importam(alvo: str, entrada: str) -> None:
    copiados = _copiados(_alvo(alvo))
    esperados = _arquivos_esperados(entrada)

    assert "COPY api/ api/" not in _alvo(alvo)
    assert esperados - copiados == set(), (
        f"O alvo {alvo} do Dockerfile não copia o que {entrada} importa: acrescente ao COPY de api/."
    )
    assert copiados - esperados == set(), (
        f"O alvo {alvo} copia o que {entrada} não importa: tire do COPY, ou a imagem muda à toa."
    )


def test_painel_nao_entra_em_nenhuma_imagem_com_gpu() -> None:
    for alvo, entrada in ALVOS.items():
        assert not {
            "api/painel.py",
            "api/resumos_de_uso.py",
            "api/main.py",
        } & _copiados(_alvo(alvo)), alvo
        assert "painel" not in _fecho(entrada)
