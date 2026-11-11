"""As imagens que rodam a API (o serviço e os três Jobs com GPU) saem com o bytecode pronto (#558)."""

from pathlib import Path

import pytest

DOCKERFILE = (Path(__file__).parents[2] / "Dockerfile").read_text()


def _alvo(inicio: str) -> str:
    """O trecho do Dockerfile do estágio que começa em `inicio`, até o próximo `\\nFROM `."""
    de = DOCKERFILE.index(inicio)
    ate = DOCKERFILE.find("\nFROM ", de + 1)
    return DOCKERFILE[de : ate if ate != -1 else None]


SERVICO = _alvo("\nFROM python:3.12-slim\n")
# Cada Job com GPU: o trecho da imagem (a da transcrição herda do `transcricao-base`, que
# vem junto) e o `uv sync` dela.
JOBS_GPU = {
    "transcricao-gpu": (
        _alvo("\nFROM python:3.12-slim-bookworm AS transcricao-base")
        + _alvo("\nFROM transcricao-base AS transcricao-gpu"),
        "uv sync --locked --no-dev --group transcricao --group transcricao-gpu",
    ),
    "ocr-gpu": (
        _alvo("\nFROM python:3.12-slim-bookworm AS ocr-gpu"),
        "uv sync --locked --no-dev --group ocr-gpu",
    ),
    "objetos-gpu": (
        _alvo("\nFROM python:3.12-slim-bookworm AS objetos-gpu"),
        "uv sync --locked --no-dev --group objetos",
    ),
}


def test_dependencias_e_pacote_da_api_vem_compilados() -> None:
    assert "uv sync --locked --no-dev --compile-bytecode" in SERVICO
    assert "compileall" in SERVICO
    # O compileall roda depois de a API ser copiada, ainda como root: os .pyc são do root,
    # só leitura como os .py, e o usuário `nobody` não consegue regravá-los.
    assert SERVICO.index("COPY api/ api/") < SERVICO.index("compileall")
    assert SERVICO.index("compileall") < SERVICO.index("USER nobody")


def test_a_imagem_do_servico_nao_desliga_o_bytecode() -> None:
    assert "PYTHONDONTWRITEBYTECODE" not in SERVICO


@pytest.mark.parametrize("alvo", JOBS_GPU)
def test_os_jobs_com_gpu_vem_compilados_como_o_servico(alvo: str) -> None:
    trecho, sync = JOBS_GPU[alvo]
    assert f"{sync} --compile-bytecode" in trecho
    # Depois de copiar os módulos da API e antes do USER: os .pyc ficam do root e só leitura.
    assert (
        trecho.rindex("api/whisper.py api/")
        < trecho.index("compileall -q api")
        < trecho.index("USER nobody")
    )
    assert "PYTHONDONTWRITEBYTECODE" not in trecho
