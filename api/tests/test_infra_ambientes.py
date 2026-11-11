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


def _texto_do_modulo() -> str:
    # Outputs e variáveis podem estar em qualquer arquivo do módulo (o balanceador.tf, #294).
    return "\n".join(f.read_text() for f in sorted(MODULO.glob("*.tf")))


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
    # Só o main.tf: os recursos dos outros arquivos do módulo nasceram nele, sem `moved`.
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
    # O `moved` da tabela apagada no apply 1 da #567 sai no apply 2.
    movidos = [m for m in movidos if m[:2] != ("google_bigquery_table", "momentos")]
    assert sorted(recursos) == sorted((t, n) for t, n, _, _ in movidos)


def test_cada_output_do_modulo_sai_na_raiz_para_o_make_e_o_deploy() -> None:
    raiz = (INFRA / "main.tf").read_text()
    saidas = re.findall(r'^output "(\w+)"', _texto_do_modulo(), re.MULTILINE)

    assert saidas
    for saida in saidas:
        assert re.search(
            rf'output "{saida}" \{{\n\s*value\s*= module\.mam\.{saida}\n', raiz
        )


def test_o_dev_e_a_producao_ligam_o_indice_ann_da_busca() -> None:
    # Sem o índice o KNN chega ao teto de 100 mil registros (ADR 0006); a produção usa o padrão.
    dev = (INFRA / "main.tf").read_text()
    prod = (INFRA / "ambientes" / "prod" / "main.tf").read_text()
    modulo = (MODULO / "main.tf").read_text()

    assert re.search(r"^\s*indices_da_busca_ligados\s*= true$", dev, re.MULTILINE)
    assert "indices_da_busca_ligados" not in prod
    assert re.search(
        r'variable "indices_da_busca_ligados" \{\n\s*type\s*= bool\n\s*default = true\n',
        modulo,
    )


def test_a_producao_tambem_exporta_o_output_dos_indices_ann_da_busca() -> None:
    prod = (INFRA / "ambientes" / "prod" / "main.tf").read_text()
    assert re.search(
        r'output "busca_indices_ligados" \{\n\s*value = module.mam.busca_indices_ligados\n',
        prod,
    )


def test_o_make_para_com_erro_se_o_output_dos_indices_falhar() -> None:
    # Um output que falha não pode virar "true": o make criaria índices caros por engano.
    linha = next(
        l
        for l in (RAIZ / "Makefile").read_text().splitlines()
        if "BUSCA_INDICES_LIGADOS=" in l and "terraform" in l
    )
    assert "|| echo" in linha


def test_as_variaveis_sem_padrao_do_modulo_sao_passadas_pela_raiz() -> None:
    raiz = (INFRA / "main.tf").read_text()
    modulo = _texto_do_modulo()
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

    chamadas = re.findall(
        r"^\s*scripts/aplicar-sem-destruir\.sh ", deploy, re.MULTILINE
    )

    assert "tf apply" not in deploy
    assert len(chamadas) == 2


def test_o_estado_de_antes_do_modulo_vai_para_ele_antes_do_apply_com_target() -> None:
    # Com `moved` pendente, o Terraform recusa um plan com -target que não cubra todos os
    # recursos movidos; sem esse apply, o repositório da GPU não existe antes das imagens.
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()
    guarda = deploy.index("ENDERECOS=$(tf state list)")
    mv = deploy.index('tf state mv "$recurso" "module.mam.$recurso"', guarda)
    com_target = deploy.index("scripts/aplicar-sem-destruir.sh -target=module.mam.", mv)
    saida_gpu = deploy.index("tf output -raw repositorio_gpu", com_target)

    assert guarda < mv < com_target < saida_gpu
    assert "grep -vE '^(module|data)\\.|^$'" in deploy[guarda:mv]
    assert "-target=module.mam.google_artifact_registry_repository.mam_gpu" in deploy


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


AMBIENTES = ("prod",)


def _sem_padrao(texto: str) -> list[str]:
    return [
        nome
        for nome, corpo in re.findall(
            r'^variable "(\w+)" \{\n(.*?)^\}', texto, re.DOTALL | re.MULTILINE
        )
        if "default" not in corpo
    ]


@pytest.mark.parametrize("ambiente", AMBIENTES)
def test_prod_chama_o_modulo_com_estado_proprio(ambiente: str) -> None:
    texto = (INFRA / "ambientes" / ambiente / "main.tf").read_text()

    assert 'source = "../../modulos/mam"' in texto
    assert f'prefix = "{ambiente}"' in texto
    backend = re.search(r'backend "gcs" \{(.*?)\n  \}', texto, re.DOTALL)
    assert backend and "bucket" not in backend.group(1)
    assert not re.search(r"^resource ", texto, re.MULTILINE)


@pytest.mark.parametrize("ambiente", AMBIENTES)
def test_prod_passa_as_variaveis_sem_padrao_do_modulo(
    ambiente: str,
) -> None:
    texto = (INFRA / "ambientes" / ambiente / "main.tf").read_text()

    for nome in _sem_padrao((MODULO / "main.tf").read_text()):
        assert re.search(rf"^\s*{nome}\s*= var\.{nome}$", texto, re.MULTILINE), nome


@pytest.mark.parametrize("ambiente", AMBIENTES)
def test_o_tfvars_de_exemplo_cobre_as_variaveis_sem_padrao(ambiente: str) -> None:
    pasta = INFRA / "ambientes" / ambiente
    exemplo = (pasta / "exemplo.tfvars").read_text()

    for nome in _sem_padrao((pasta / "main.tf").read_text()):
        assert re.search(rf"^{nome}\s*=", exemplo, re.MULTILINE), nome
    assert "redetv" not in exemplo.lower()


def test_o_ci_valida_dev_e_prod() -> None:
    ci = (RAIZ / ".github" / "workflows" / "ci.yml").read_text()

    for pasta in ("infra", "infra/ambientes/prod"):
        init = ci.index(f"terraform -chdir={pasta} init -backend=false")
        assert init < ci.index(f"terraform -chdir={pasta} validate")
    # O plano simulado roda no CI, depois do validate do dev.
    assert ci.index("terraform -chdir=infra validate") < ci.index(
        "terraform -chdir=infra test"
    )
    assert (INFRA / "plano_simulado.tftest.hcl").exists()


def test_o_readme_da_infra_tem_a_tabela_e_a_lista_do_que_precisa_existir() -> None:
    readme = (INFRA / "README.md").read_text()

    for ambiente in ("dev", "prod"):
        assert f"| {ambiente} |" in readme
    assert "staging" not in readme
    assert "#294" in readme and "#296" in readme


def test_o_readme_lista_os_papeis_da_terraform_do_wizard_e_os_da_build() -> None:
    readme = (INFRA / "README.md").read_text()
    wizard = (RAIZ / "scripts" / "wizard-gcp-dev.sh").read_text()
    bloco = re.search(
        r"^PAPEIS_DA_TERRAFORM=\((.*?)^\)", wizard, re.DOTALL | re.MULTILINE
    )
    assert bloco
    papeis = re.findall(r"^\s*(roles/[\w.]+)", bloco.group(1), re.MULTILINE)

    assert papeis
    for papel in papeis:
        assert f"- `{papel}`" in readme, papel
    for papel in re.findall(
        r'role\s*= "(roles/[\w.]+)"\n\s*member\s*= google_service_account\.mam\["build"\]',
        (MODULO / "main.tf").read_text(),
    ) + ["roles/logging.logWriter"]:
        assert f"`{papel}`" in readme, papel
