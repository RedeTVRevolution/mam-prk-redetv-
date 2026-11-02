"""Tirar o Editor da conta padrão do Compute e apagar a rede default (#301)."""

import os
import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).parents[2]
MODULO = RAIZ / "infra" / "modulos" / "mam"
MAIN = (MODULO / "conta_padrao.tf").read_text()
SCRIPT = RAIZ / "scripts" / "apagar-rede-default.sh"


def _bloco(texto: str, cabecalho: str) -> str:
    inicio = texto.index(cabecalho)
    return texto[inicio : texto.index("\n}\n", inicio)]


def test_o_editor_sai_da_conta_padrao_so_por_remocao_pontual() -> None:
    bloco = _bloco(
        MAIN, 'resource "google_project_iam_member_remove" "editor_da_conta_padrao"'
    )

    assert 'role    = "roles/editor"' in bloco
    assert "-compute@developer.gserviceaccount.com" in bloco
    assert "data.google_project" in bloco
    main = (MODULO / "main.tf").read_text()
    assert not re.search(
        r"^resource \"google_project_iam_(policy|binding)\"", main, re.MULTILINE
    )


def test_a_adr_0002_traz_a_excecao() -> None:
    adr = next((RAIZ / "docs" / "adr").glob("0002*")).read_text()

    assert "google_project_iam_member_remove" in adr
    assert "roles/editor" in adr


def _gcloud_falso(tmp_path: Path, existe: bool) -> tuple[dict[str, str], Path]:
    registro = tmp_path / "chamadas"
    falso = tmp_path / "bin" / "gcloud"
    falso.parent.mkdir()
    falso.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$*" >> "$REGISTRO"\n'
        'case "$*" in\n'
        '  *"networks describe"*) [[ $REDE_EXISTE == sim ]] || exit 1 ;;\n'
        '  *"firewall-rules list"*) echo default-allow-ssh; echo default-allow-icmp ;;\n'
        "esac\n"
    )
    falso.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{falso.parent}:{os.environ['PATH']}",
        "REGISTRO": str(registro),
        "REDE_EXISTE": "sim" if existe else "nao",
        "GCP_PROJECT_ID": "p",
        "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": "t@p.iam.gserviceaccount.com",
    }
    return env, registro


def test_o_script_apaga_as_regras_e_depois_a_rede(tmp_path: Path) -> None:
    env, registro = _gcloud_falso(tmp_path, existe=True)

    subprocess.run([str(SCRIPT)], env=env, check=True, capture_output=True)

    chamadas = registro.read_text().splitlines()
    apagadas = [c for c in chamadas if " delete " in c]
    assert "firewall-rules delete default-allow-ssh" in apagadas[0]
    assert "firewall-rules delete default-allow-icmp" in apagadas[1]
    assert "networks delete default" in apagadas[2]
    assert len(apagadas) == 3


def test_sem_a_rede_default_o_script_nao_apaga_nada(tmp_path: Path) -> None:
    env, registro = _gcloud_falso(tmp_path, existe=False)

    subprocess.run([str(SCRIPT)], env=env, check=True, capture_output=True)

    assert " delete " not in registro.read_text()


def test_o_deploy_do_dev_chama_o_script_depois_do_apply_completo() -> None:
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()

    assert deploy.rindex("scripts/aplicar-sem-destruir.sh") < deploy.index(
        "scripts/apagar-rede-default.sh"
    )
