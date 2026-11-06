"""O workflow do CI (#290), lido como texto: sem PyYAML no projeto."""

import re
import subprocess
from pathlib import Path

import pytest

CI = (Path(__file__).parents[2] / ".github" / "workflows" / "ci.yml").read_text()


def _jobs() -> list[str]:
    bloco = CI[CI.index("\njobs:\n") :]
    return re.findall(r"^  ([a-z-]+):$", bloco, re.MULTILINE)


def test_nenhuma_chave_de_topo_se_repete() -> None:
    # O GitHub recusa o workflow inteiro com chave duplicada; o parse do PyYAML não.
    chaves = re.findall(r"^([a-z_-]+):", CI, re.MULTILINE)
    assert len(chaves) == len(set(chaves)), chaves


def test_nenhum_job_se_repete() -> None:
    jobs = _jobs()
    assert len(jobs) == len(set(jobs)), jobs


def test_o_publicar_espera_todos_os_outros_jobs() -> None:
    necessarios = re.search(r"^    needs: \[(.*)\]$", CI, re.MULTILINE)
    assert necessarios
    esperados = {j.strip() for j in necessarios.group(1).split(",")}
    assert esperados == set(_jobs()) - {"publicar"}


SCRIPT = Path(__file__).parents[2] / "scripts" / "vai-para-a-nuvem.sh"


def _vai_para_a_nuvem(*caminhos: str) -> bool:
    entrada = "".join(f"{c}\n" for c in caminhos)
    saida = subprocess.run([SCRIPT], input=entrada, text=True, check=False)
    assert saida.returncode in (0, 1), saida
    return saida.returncode == 0


@pytest.mark.parametrize(
    "caminhos",
    [
        ("docs/Plano_MAM.md", "docs/api/openapi.json", "GLOSSARY.md"),
        ("README.md", "AGENTS.md", "infra/README.md", ".gitignore"),
        ("evals/gabarito/README.md", "scripts/afk/main.mts", ".claude/settings.json"),
        ("api/tests/test_busca.py", ".githooks/pre-commit", "docs/migração.md"),
        (),
    ],
)
def test_so_documentacao_nao_publica(caminhos: tuple[str, ...]) -> None:
    assert not _vai_para_a_nuvem(*caminhos)


@pytest.mark.parametrize(
    "caminhos",
    [
        ("api/x.py",),
        ("docs/Plano_MAM.md", "api/x.py", "README.md"),
        ("web/src/App.tsx",),
        ("api/LEIA.md",),
        ("infra/modulos/mam/main.tf",),
        ("infra/modulos/mam/resumos_de_uso.sql",),
        ("Dockerfile",),
        ("docker-bake.hcl",),
        ("cloudbuild.yaml",),
        (".dockerignore",),
        (".gcloudignore",),
        ("Makefile",),
        ("pyproject.toml",),
        ("uv.lock",),
        (".github/workflows/ci.yml",),
        ("scripts/deploy-dev.sh",),
        ("scripts/baixar-modelos-ocr.sh",),
        ("arquivo-novo-na-raiz",),
    ],
)
def test_o_que_vai_para_a_nuvem_publica(caminhos: tuple[str, ...]) -> None:
    assert _vai_para_a_nuvem(*caminhos)


def test_o_publicar_espera_o_mudou_o_deploy_e_confere_o_que_veio_depois() -> None:
    publicar = CI[CI.index("\n  publicar:\n") :]
    assert "needs.mudou-o-deploy.outputs.pula != '1'" in publicar
    assert "scripts/vai-para-a-nuvem.sh" in publicar


def test_mover_codigo_para_docs_publica(tmp_path: Path) -> None:
    # Com renomeação, o diff só mostra o destino (docs/x.py) e esconderia a
    # saída de api/x.py da imagem; por isso os dois diffs usam --no-renames.
    assert CI.count("diff --no-renames --name-only") == 2

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    git("init", "-q")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "x.py").write_text("print('oi')\n")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "a")
    (tmp_path / "docs").mkdir()
    git("mv", "api/x.py", "docs/x.py")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "b")
    mudou = git("diff", "--no-renames", "--name-only", "HEAD~1", "HEAD").split()
    assert _vai_para_a_nuvem(*mudou)
