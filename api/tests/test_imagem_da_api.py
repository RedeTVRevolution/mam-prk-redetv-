"""A imagem do serviço (último alvo do Dockerfile) sai com o bytecode pronto (#558)."""

from pathlib import Path

DOCKERFILE = (Path(__file__).parents[2] / "Dockerfile").read_text()
SERVICO = DOCKERFILE[DOCKERFILE.rindex("\nFROM python:3.12-slim\n") :]


def test_dependencias_e_pacote_da_api_vem_compilados() -> None:
    assert "uv sync --locked --no-dev --compile-bytecode" in SERVICO
    assert "compileall" in SERVICO
    # O compileall roda depois de a API ser copiada, ainda como root: os .pyc são do root,
    # só leitura como os .py, e o usuário `nobody` não consegue regravá-los.
    assert SERVICO.index("COPY api/ api/") < SERVICO.index("compileall")
    assert SERVICO.index("compileall") < SERVICO.index("USER nobody")


def test_a_imagem_do_servico_nao_desliga_o_bytecode() -> None:
    assert "PYTHONDONTWRITEBYTECODE" not in SERVICO
