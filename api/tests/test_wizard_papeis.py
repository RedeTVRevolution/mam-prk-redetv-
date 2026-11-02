import re
from pathlib import Path

WIZARD = Path(__file__).resolve().parents[2] / "scripts" / "wizard-gcp-dev.sh"

PAPEIS_DE_ANTES = [
    "resourcemanager.projectIamAdmin",
    "serviceusage.serviceUsageAdmin",
    "iam.serviceAccountAdmin",
    "iam.serviceAccountUser",
    "run.admin",
    "storage.admin",
    "artifactregistry.admin",
    "datastore.owner",
    "eventarc.admin",
    "workflows.admin",
    "identityplatform.admin",
    "monitoring.editor",
    "logging.configWriter",
    "compute.networkAdmin",
    "iam.workloadIdentityPoolAdmin",
    "cloudbuild.builds.editor",
]
PAPEIS_NOVOS = [
    "secretmanager.admin",
    "cloudscheduler.admin",
    "bigquery.admin",
    "cloudkms.admin",
    "pubsub.admin",
    "compute.loadBalancerAdmin",
    "certificatemanager.owner",
    "compute.securityAdmin",
    "iam.roleAdmin",
]


def _linhas_dos_papeis() -> list[str]:
    texto = WIZARD.read_text()
    inicio = texto.index("PAPEIS_DA_TERRAFORM=(")
    fim = texto.index("\n)", inicio)
    return texto[inicio:fim].splitlines()[1:]


def test_wizard_da_os_25_papeis_a_mam_terraform() -> None:
    papeis = [
        m.group(1)
        for linha in _linhas_dos_papeis()
        if (m := re.match(r"\s*roles/(\S+)", linha))
    ]
    assert papeis == PAPEIS_DE_ANTES + PAPEIS_NOVOS


def test_cada_papel_novo_tem_comentario_na_mesma_linha() -> None:
    linhas = _linhas_dos_papeis()
    for papel in PAPEIS_NOVOS:
        linha = next(item for item in linhas if f"roles/{papel} " in item + " ")
        assert re.search(r"#\s*\S", linha), papel


def test_regra_do_papel_a_mao_esta_acima_da_lista() -> None:
    texto = WIZARD.read_text()
    regra = "Papel dado à mão à mam-terraform entra aqui no mesmo dia."
    assert regra in texto
    assert texto.index(regra) < texto.index("PAPEIS_DA_TERRAFORM=(")


def test_agents_md_traz_a_regra() -> None:
    agents = (WIZARD.parents[1] / "AGENTS.md").read_text()
    assert (
        "Todo papel dado à mão à conta mam-terraform entra no scripts/wizard-gcp-dev.sh "
        "no mesmo dia, com uma linha dizendo para que serve."
    ) in agents
