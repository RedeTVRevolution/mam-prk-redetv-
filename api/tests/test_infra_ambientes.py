"""O módulo do Terraform e a proteção contra destruição no deploy (#292)."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[2]
INFRA = RAIZ / "infra"
MODULO = INFRA / "modulos" / "mam"
SCRIPT = RAIZ / "scripts" / "aplicar-sem-destruir.sh"


def _enderecos(texto: str, tipo: str) -> list[str]:
    return re.findall(rf'^{tipo} "(\w+)" "(\w+)"', texto, re.MULTILINE)


def test_o_dev_chama_o_modulo_e_o_modulo_nao_tem_backend_nem_provider() -> None:
    raiz = (INFRA / "main.tf").read_text()
    modulo = (MODULO / "main.tf").read_text()

    assert 'source = "./modulos/mam"' in raiz
    assert 'backend "gcs"' in raiz and 'prefix = "dev"' in raiz
    assert 'provider "google"' in raiz
    assert 'backend "' not in modulo and 'provider "google"' not in modulo
    assert not re.search(r"^resource ", raiz, re.MULTILINE)


def test_cada_recurso_do_modulo_tem_o_seu_bloco_moved() -> None:
    raiz = (INFRA / "main.tf").read_text()
    recursos = re.findall(
        r'^resource "(\w+)" "(\w+)"', (MODULO / "main.tf").read_text(), re.MULTILINE
    )
    movidos = re.findall(
        r"moved \{\s*from = (\w+)\.(\w+)\s*to\s*= module\.mam\.(\w+)\.(\w+)\s*\}", raiz
    )

    assert recursos
    assert all(
        de_tipo == para_tipo and de_nome == para_nome
        for de_tipo, de_nome, para_tipo, para_nome in movidos
    )
    assert sorted(recursos) == sorted((t, n) for t, n, _, _ in movidos)


def test_cada_output_do_modulo_sai_na_raiz_para_o_make_e_o_deploy() -> None:
    raiz = (INFRA / "main.tf").read_text()
    saidas = re.findall(
        r'^output "(\w+)"', (MODULO / "main.tf").read_text(), re.MULTILINE
    )

    assert saidas
    for saida in saidas:
        assert re.search(
            rf'output "{saida}" \{{\n\s*value\s*= module\.mam\.{saida}\n', raiz
        )


def test_as_variaveis_sem_padrao_do_modulo_sao_passadas_pela_raiz() -> None:
    raiz = (INFRA / "main.tf").read_text()
    modulo = (MODULO / "main.tf").read_text()
    sem_padrao = [
        nome
        for nome, corpo in re.findall(
            r'^variable "(\w+)" \{\n(.*?)^\}', modulo, re.DOTALL | re.MULTILINE
        )
        if "default" not in corpo
    ]

    assert sem_padrao
    for nome in sem_padrao:
        assert f'variable "{nome}"' in raiz
        assert re.search(rf"^\s*{nome}\s*= var\.{nome}$", raiz, re.MULTILINE)


def test_o_deploy_aplica_so_pelo_script_que_recusa_destruicao() -> None:
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()

    assert "tf apply" not in deploy
    assert deploy.count("scripts/aplicar-sem-destruir.sh") >= 3  # 2 usos e o comentário


# O terraform falso grava o que recebeu e devolve o plano de `$FALSO/plano.json`.
TERRAFORM_FALSO = r"""#!/usr/bin/env bash
echo "$*" >>"$FALSO/chamadas"
for a in "$@"; do
  case $a in
    plan) acao=plan ;;
    show) acao=show ;;
    apply) acao=apply ;;
  esac
done
[[ $acao == show ]] && cat "$FALSO/plano.json"
exit 0
"""


def _plano(*mudancas: tuple[str, list[str]]) -> str:
    return json.dumps(
        {
            "resource_changes": [
                {"address": endereco, "change": {"actions": acoes}}
                for endereco, acoes in mudancas
            ]
        }
    )


def _rodar(
    tmp_path: Path, plano: str, **ambiente: str
) -> subprocess.CompletedProcess[str]:
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "terraform").write_text(TERRAFORM_FALSO)
    (bin_ / "terraform").chmod(0o755)
    (tmp_path / "plano.json").write_text(plano)
    return subprocess.run(
        [str(SCRIPT), "-var", "imagem=x"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **{k: v for k, v in os.environ.items() if k != "PERMITIR_DESTRUICAO"},
            "PATH": f"{bin_}:{os.environ['PATH']}",
            "FALSO": str(tmp_path),
            **ambiente,
        },
    )


def _chamadas(tmp_path: Path) -> list[str]:
    return (tmp_path / "chamadas").read_text().splitlines()


@pytest.mark.parametrize(
    "mudancas",
    [
        [("module.mam.google_x.a", ["no-op"]), ("module.mam.google_x.b", ["update"])],
        [("module.mam.google_x.a", ["create"])],
        [],
    ],
)
def test_plano_sem_destruicao_e_aplicado(
    tmp_path: Path, mudancas: list[tuple[str, list[str]]]
) -> None:
    r = _rodar(tmp_path, _plano(*mudancas))

    assert r.returncode == 0, r.stderr
    chamadas = _chamadas(tmp_path)
    assert any(" plan " in f" {c} " and "-var imagem=x" in c for c in chamadas)
    assert any(" apply " in f" {c} " for c in chamadas)


@pytest.mark.parametrize(
    "acoes", [["delete"], ["delete", "create"], ["create", "delete"]]
)
def test_plano_com_destruicao_ou_recriacao_para_sem_aplicar(
    tmp_path: Path, acoes: list[str]
) -> None:
    r = _rodar(
        tmp_path,
        _plano(("module.mam.google_x.a", ["no-op"]), ("module.mam.google_x.b", acoes)),
    )

    assert r.returncode != 0
    assert "module.mam.google_x.b" in r.stderr
    assert "module.mam.google_x.a" not in r.stderr
    assert not any(" apply " in f" {c} " for c in _chamadas(tmp_path))


def test_destruicao_so_passa_com_a_variavel_explicita(tmp_path: Path) -> None:
    plano = _plano(("module.mam.google_x.b", ["delete", "create"]))

    assert _rodar(tmp_path, plano, PERMITIR_DESTRUICAO="nao").returncode != 0
    r = _rodar(tmp_path, plano, PERMITIR_DESTRUICAO="sim")

    assert r.returncode == 0, r.stderr
    assert any(" apply " in f" {c} " for c in _chamadas(tmp_path))
