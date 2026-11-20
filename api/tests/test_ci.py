"""O workflow do CI (#290), lido como texto: sem PyYAML no projeto."""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

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
        (
            "evals/gabarito/README.md",
            "scripts/afk/main.mts",
            ".claude/settings.json",
            "scripts/copy_das_imagens_gpu.py",
        ),
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


# O mudou-o-deploy compara com o último deploy de fato (scripts/ultimo-deploy.sh).
ULTIMO_DEPLOY = Path(__file__).parents[2] / "scripts" / "ultimo-deploy.sh"


Tentativa = tuple[
    str | None, int
]  # conclusão do passo do deploy (None: não rodou), minuto


def _ultimo_deploy(
    tmp_path: Path,
    runs: list[tuple[str, str, list[Tentativa]]],
    anteriores_do_atual: list[Tentativa] | None = None,
) -> subprocess.CompletedProcess[str]:
    """`runs`: (sha, status do run, tentativas do `publicar`), do push mais novo ao mais
    antigo, como a API devolve; o run atual (id 99) vem antes, na tentativa que roda agora. Cada tentativa
    diz como terminou o passo do deploy e o minuto em que terminou. Um sha "sem-resposta"
    não tem arquivo de jobs: a consulta falha. `anteriores_do_atual`: as tentativas já
    terminadas do run atual, que roda na tentativa seguinte."""
    anteriores = anteriores_do_atual or []
    lista = []
    todos = [("atual", "in_progress", [*anteriores, ("in_progress", 59)]), *runs]
    for id, (sha, status, tentativas) in zip(
        [99, *range(1, len(runs) + 1)], todos, strict=True
    ):
        lista.append({"id": id, "head_sha": sha, "status": status})
        if sha == "sem-resposta":
            continue
        jobs: list[dict[str, Any]] = [{"name": "backend", "head_sha": sha, "steps": []}]
        for tentativa, (conclusao, minuto) in enumerate(tentativas, start=1):
            fim = f"2026-11-19T10:{minuto:02d}:00Z"
            passos = [
                {"name": "Deploy no dev", "conclusion": conclusao, "completed_at": fim}
            ]
            jobs.append(
                {
                    "name": "publicar",
                    "head_sha": sha,
                    "run_id": id,
                    "run_attempt": tentativa,
                    "steps": passos if conclusao else [],
                }
            )
        (tmp_path / f"jobs-{id}.json").write_text(json.dumps({"jobs": jobs}))
    (tmp_path / "runs.json").write_text(json.dumps({"workflow_runs": lista}))
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        "url=${*: -1}\n"
        "case $url in\n"
        '  */workflows/*) cat "$FALSO/runs.json" ;;\n'
        '  */jobs?filter=all\\&per_page=100) id=${url#*/runs/}; cat "$FALSO/jobs-${id%%/*}.json" ;;\n'
        "  *) exit 9 ;;\n"
        "esac\n"
    )
    gh.chmod(0o755)
    ambiente = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FALSO": str(tmp_path),
        "GITHUB_REPOSITORY": "dono/repo",
        "GITHUB_RUN_ID": "99",
        "GITHUB_RUN_ATTEMPT": str(len(anteriores) + 1),
    }
    return subprocess.run(
        [ULTIMO_DEPLOY], env=ambiente, text=True, capture_output=True, check=False
    )


FIM = "completed"


def test_o_ultimo_deploy_e_o_que_publicou_de_fato(tmp_path: Path) -> None:
    saida = _ultimo_deploy(
        tmp_path,
        [
            (
                "so-teste",
                FIM,
                [(None, 40)],
            ),  # publicar pulado: o passo do deploy nem roda
            ("backend-falhou", FIM, [("skipped", 30)]),
            ("publicou", FIM, [("success", 20)]),
            ("antigo", FIM, [("success", 10)]),
        ],
    )
    assert saida.returncode == 0, saida.stderr
    assert saida.stdout.strip() == "publicou"


def test_conta_o_deploy_de_uma_tentativa_anterior_do_mesmo_run(tmp_path: Path) -> None:
    # Reexecutado com outra ponta, o `publicar` pula; o deploy da 1ª tentativa segue no dev.
    saida = _ultimo_deploy(
        tmp_path,
        [
            ("reexecutado", FIM, [("success", 20), (None, 50)]),
            ("antigo", FIM, [("success", 10)]),
        ],
    )
    assert saida.returncode == 0, saida.stderr
    assert saida.stdout.strip() == "reexecutado"


def test_vale_o_deploy_que_terminou_por_ultimo_nao_o_push_mais_novo(
    tmp_path: Path,
) -> None:
    # Um push antigo pode publicar depois de um mais novo (o `ponta` deixa, se a árvore
    # que vai para a nuvem voltou a ser a dele).
    saida = _ultimo_deploy(
        tmp_path,
        [("novo", FIM, [("success", 20)]), ("atrasado", FIM, [("success", 30)])],
    )
    assert saida.returncode == 0, saida.stderr
    assert saida.stdout.strip() == "atrasado"


def test_conta_as_tentativas_anteriores_do_proprio_run(tmp_path: Path) -> None:
    # A 1ª tentativa deste run publicou e falhou: reexecutado, o dev segue incerto.
    saida = _ultimo_deploy(
        tmp_path,
        [("publicou", FIM, [("success", 20)])],
        anteriores_do_atual=[("failure", 40)],
    )
    assert saida.returncode != 0
    assert saida.stdout.strip() == ""


@pytest.mark.parametrize(
    "incerto",
    [
        # Ainda publicando: um revert dele para a árvore do último deploy não pode pular.
        ("rodando", "in_progress", []),
        # Falhou ou foi cancelado depois de mexer na nuvem.
        ("deploy-falhou", FIM, [("failure", 30)]),
        ("deploy-cancelado", FIM, [("cancelled", 30)]),
        # A API não respondeu: não dá para saber se publicou.
        ("sem-resposta", FIM, []),
    ],
)
def test_dev_incerto_sai_com_erro_e_o_ci_publica(
    tmp_path: Path, incerto: tuple[str, str, list[Tentativa]]
) -> None:
    saida = _ultimo_deploy(tmp_path, [incerto, ("publicou", FIM, [("success", 20)])])
    assert saida.returncode != 0
    assert saida.stdout.strip() == ""


def test_sem_deploy_conhecido_sai_com_erro_e_o_ci_publica(tmp_path: Path) -> None:
    saida = _ultimo_deploy(tmp_path, [("so-teste", FIM, [(None, 10)])])
    assert saida.returncode != 0
    assert saida.stdout.strip() == ""


def test_o_mudou_o_deploy_compara_com_o_ultimo_deploy() -> None:
    mudou = CI[CI.index("\n  mudou-o-deploy:\n") : CI.index("\n  publicar:\n")]
    assert "scripts/ultimo-deploy.sh" in mudou
    assert "github.event.before" not in mudou
    assert "actions: read" in mudou
    # O script acha o deploy pelo nome do passo.
    publicar = CI[CI.index("\n  publicar:\n") :]
    assert "- name: Deploy no dev\n" in publicar
