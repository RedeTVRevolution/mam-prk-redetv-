"""As versões que o CI, o loop AFK e as imagens repetem ficam iguais (#759)."""

import re
from pathlib import Path

RAIZ = Path(__file__).parents[2]


def _ler(caminho: str) -> str:
    return (RAIZ / caminho).read_text()


DOCKERFILE = _ler("Dockerfile")
AFK = _ler("scripts/afk/Dockerfile")
CI = _ler(".github/workflows/ci.yml")


def _um(padrao: str, texto: str) -> str:
    achados = re.findall(padrao, texto, re.MULTILINE)
    assert len(achados) == 1, (padrao, achados)
    return achados[0]


def test_uv_e_python_do_dockerfile_e_do_afk_sao_os_mesmos() -> None:
    assert _um(r"^ARG UV_VERSAO=(\S+)$", DOCKERFILE) == _um(
        r"astral-sh/uv:(\S+) /uv", AFK
    )
    assert _um(r"^ARG PYTHON_BASE=(\S+)$", DOCKERFILE) == _um(
        r"^FROM (python:\S+)$", AFK
    )


def test_emuladores_do_afk_e_da_acao_do_ci_sao_os_mesmos() -> None:
    imagens = r"(fsouza/fake-gcs-server:[^\s"']+|google/cloud-sdk:[^\s"']+)"
    afk = set(re.findall(imagens, _ler("scripts/afk/rodar.sh")))
    ci = set(re.findall(imagens, _ler(".github/actions/emuladores/action.yml")))
    assert len(afk) == 2 and afk == ci


def test_gitleaks_do_afk_e_do_ci_sao_os_mesmos() -> None:
    assert _um(r"^ARG GITLEAKS_VERSION=(\S+)$", AFK) == _um(
        r"Instala o gitleaks (\S+)", CI
    )
    # O CI roda em x64: a soma é a do ramo x64 do loop AFK.
    assert _um(r"\*\) gl=x64; gl_sha=(\w{64})", AFK) == _um(
        r'echo "(\w{64})  gitleaks.tar.gz"', CI
    )
    # A versão no diretório da release e no nome do artefato, nas duas pontas.
    versao = _um(r"^ARG GITLEAKS_VERSION=(\S+)$", AFK)
    assert _um(r"download/v(\S+)/gitleaks_\S+_linux_x64\.tar\.gz", CI) == versao
    assert _um(r"download/v\S+/gitleaks_(\S+)_linux_x64\.tar\.gz", CI) == versao
    assert "download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_" in AFK


def test_alvo_validacao_sai_com_bytecode_pronto() -> None:
    alvo = DOCKERFILE[DOCKERFILE.index("AS validacao") :].split("\nFROM ")[0]
    assert "uv sync --locked --no-dev --compile-bytecode" in alvo
    compilar = "RUN /app/.venv/bin/python -m compileall -q api"
    assert (
        alvo.index("COPY api/ api/") < alvo.index(compilar) < alvo.index("USER nobody")
    )
    assert "PYTHONDONTWRITEBYTECODE=1" in alvo
