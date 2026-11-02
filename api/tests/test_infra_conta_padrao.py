"""Tirar o Editor da conta padrão do Compute e apagar a rede default (#301)."""

import os
import re
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[2]
MODULO = RAIZ / "infra" / "modulos" / "mam"
CONTA_PADRAO = (MODULO / "conta_padrao.tf").read_text()
SCRIPT = RAIZ / "scripts" / "apagar-rede-default.sh"


def _bloco(texto: str, cabecalho: str) -> str:
    inicio = texto.index(cabecalho)
    return texto[inicio : texto.index("\n}\n", inicio)]


def test_o_editor_sai_da_conta_padrao_so_por_remocao_pontual() -> None:
    bloco = _bloco(
        CONTA_PADRAO,
        'resource "google_project_iam_member_remove" "editor_da_conta_padrao"',
    )

    assert 'role    = "roles/editor"' in bloco
    assert (
        'member  = "serviceAccount:${data.google_project.este.number}'
        '-compute@developer.gserviceaccount.com"'
    ) in bloco
    assert "depends_on = [google_project_service.apis]" in bloco
    for tf in MODULO.glob("*.tf"):
        assert not re.search(
            r"^resource \"google_project_iam_(policy|binding)\"",
            tf.read_text(),
            re.MULTILINE,
        ), tf.name


def test_a_adr_0002_traz_a_excecao() -> None:
    adr = next((RAIZ / "docs" / "adr").glob("0002*")).read_text()

    assert "google_project_iam_member_remove" in adr
    assert "roles/editor" in adr


def _gcloud_falso(tmp_path: Path, rede: str = "existe") -> tuple[dict[str, str], Path]:
    """`rede`: existe, nao_existe ou sem_acesso (a listagem falha)."""
    registro = tmp_path / "chamadas"
    falso = tmp_path / "bin" / "gcloud"
    falso.parent.mkdir()
    # As regras só voltam com o filtro da rede default; a regra de outra rede só voltaria
    # a um script que listasse sem filtro.
    falso.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$*" >> "$REGISTRO"\n'
        'case "$*" in\n'
        '  *"networks list"*)\n'
        '    [[ $REDE == sem_acesso ]] && { echo "PERMISSION_DENIED" >&2; exit 1; }\n'
        "    if [[ $REDE == existe ]]; then echo default; fi ;;\n"
        '  *"firewall-rules list --filter=network~/networks/default$ "*)\n'
        "    echo default-allow-ssh; echo default-allow-icmp ;;\n"
        '  *"firewall-rules list"*) echo mam-validacao-saida ;;\n'
        "esac\n"
    )
    falso.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{falso.parent}:{os.environ['PATH']}",
        "REGISTRO": str(registro),
        "REDE": rede,
        "GCP_PROJECT_ID": "p",
        "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": "t@p.iam.gserviceaccount.com",
    }
    return env, registro


def test_o_script_apaga_so_as_regras_da_default_e_depois_a_rede(
    tmp_path: Path,
) -> None:
    env, registro = _gcloud_falso(tmp_path)

    subprocess.run([str(SCRIPT)], env=env, check=True, capture_output=True)

    apagadas = [c for c in registro.read_text().splitlines() if " delete " in c]
    assert "firewall-rules delete default-allow-ssh" in apagadas[0]
    assert "firewall-rules delete default-allow-icmp" in apagadas[1]
    assert "networks delete default" in apagadas[2]
    assert len(apagadas) == 3


def test_sem_a_rede_default_o_script_nao_apaga_nada(tmp_path: Path) -> None:
    env, registro = _gcloud_falso(tmp_path, rede="nao_existe")

    subprocess.run([str(SCRIPT)], env=env, check=True, capture_output=True)

    assert " delete " not in registro.read_text()


def test_erro_de_acesso_nao_passa_por_rede_ja_apagada(tmp_path: Path) -> None:
    env, registro = _gcloud_falso(tmp_path, rede="sem_acesso")

    with pytest.raises(subprocess.CalledProcessError) as erro:
        subprocess.run([str(SCRIPT)], env=env, check=True, capture_output=True)

    assert b"j\xc3\xa1 n\xc3\xa3o existe" not in erro.value.stdout
    assert " delete " not in registro.read_text()


def test_o_deploy_do_dev_apaga_a_rede_por_ultimo() -> None:
    linhas = [
        linha.strip()
        for linha in (RAIZ / "scripts" / "deploy-dev.sh").read_text().splitlines()
        if linha.strip() and not linha.strip().startswith("#")
    ]
    chamada = next(
        i
        for i, linha in enumerate(linhas)
        if linha.startswith("scripts/apagar-rede-default.sh")
    )

    assert chamada == len(linhas) - 1
    assert any(
        linha.startswith("scripts/aplicar-sem-destruir.sh")
        for linha in linhas[:chamada]
    )
    assert any("scripts/testar-jobs-gpu.sh" in linha for linha in linhas[:chamada])
