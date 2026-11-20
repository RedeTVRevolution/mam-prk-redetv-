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
    assert sorted(recursos) == sorted((t, n) for t, n, _, _ in movidos)


def _saidas(texto: str) -> list[str]:
    return re.findall(r'^output "(\w+)"', texto, re.MULTILINE)


RAIZES = {"dev": INFRA / "main.tf", "prod": INFRA / "ambientes" / "prod" / "main.tf"}


def _texto_da_raiz(raiz: Path) -> str:
    # Todos os .tf da pasta da raiz, não só o main.tf.
    return "\n".join(f.read_text() for f in sorted(raiz.parent.glob("*.tf")))


@pytest.mark.parametrize("raiz", RAIZES)
def test_cada_output_do_modulo_sai_na_raiz_para_o_make_e_o_deploy(raiz: str) -> None:
    texto = RAIZES[raiz].read_text()
    saidas = _saidas(_texto_do_modulo())

    assert saidas
    for saida in saidas:
        assert re.search(
            rf'output "{saida}" \{{\n\s*value\s*= module\.mam\.{saida}\n', texto
        ), saida


def test_o_dev_e_a_producao_exportam_os_mesmos_outputs() -> None:
    assert sorted(_saidas(RAIZES["dev"].read_text())) == sorted(
        _saidas(RAIZES["prod"].read_text())
    )


def test_o_output_sensivel_continua_sensivel_nas_duas_raizes() -> None:
    for raiz in RAIZES.values():
        assert re.search(
            r'output "identity_api_key" \{\n\s*value\s*= module\.mam\.identity_api_key\n\s*sensitive = true',
            raiz.read_text(),
        )


def test_nenhuma_raiz_exporta_o_projeto() -> None:
    # GCP_PROJECT_ID segue vindo do arquivo de ambiente.
    for raiz in RAIZES.values():
        assert not {"projeto", "gcp_project_id"} & set(_saidas(raiz.read_text()))


def test_nenhum_tf_fora_do_modulo_escreve_nome_de_recurso() -> None:
    # Só o módulo monta nomes (AGENTS.md); `mam-principal` era o caso nas raízes.
    for raiz in RAIZES.values():
        assert not re.search(r'"mam-[a-z0-9-]+"', _texto_da_raiz(raiz)), raiz


def _padrao(texto: str, nome: str) -> str | None:
    corpo = re.search(
        rf'^variable "{nome}" \{{\n(.*?)^\}}', texto, re.DOTALL | re.MULTILINE
    )
    assert corpo, nome
    padrao = re.search(r"^\s*default\s*= (.+)$", corpo.group(1), re.MULTILINE)
    return padrao.group(1).strip() if padrao else None


@pytest.mark.parametrize("raiz", RAIZES)
def test_o_padrao_de_cada_variavel_da_raiz_e_o_do_modulo(raiz: str) -> None:
    texto = _texto_da_raiz(RAIZES[raiz])
    modulo = _texto_do_modulo()
    redeclaradas = [
        n
        for n in re.findall(r'^variable "(\w+)"', texto, re.MULTILINE)
        if _padrao(texto, n) is not None
    ]

    assert redeclaradas
    for nome in redeclaradas:
        assert _padrao(texto, nome) == _padrao(modulo, nome), nome


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


def test_o_ponto_unico_para_com_erro_se_o_output_dos_indices_falhar() -> None:
    # Um output que falha não pode virar "true": o make criaria índices caros por engano. A leitura
    # que falha para o alvo; o output ausente vira texto inválido, e o código para com erro.
    script = (RAIZ / "scripts" / "ler-ambiente.sh").read_text()
    makefile = (RAIZ / "Makefile").read_text()
    ambiente = makefile[makefile.index("AMBIENTE_DA_BUSCA = ") :].split("\n\n")[0]

    assert "BUSCA_INDICES_LIGADOS" in ambiente
    assert "valor=terraform_output_falhou" in script


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
    saida_gpu = deploy.index("ler_ambiente REPOSITORIO=repositorio", com_target)

    assert guarda < mv < com_target < saida_gpu
    assert "grep -vE '^(module|data)\\.|^$'" in deploy[guarda:mv]
    assert "-target=module.mam.google_artifact_registry_repository.mam_gpu" in deploy


def test_o_deploy_move_os_sinais_percentuais_no_estado_antes_do_apply_com_target() -> (
    None
):
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()
    com_target = deploy.index("scripts/aplicar-sem-destruir.sh -target=module.mam.")
    antes = deploy[:com_target]

    for recurso in (
        "google_logging_metric.sinal_percentual",
        "google_monitoring_alert_policy.sinal_percentual",
    ):
        assert recurso in antes
    # Só move quando o endereço antigo (com chave) existe no estado.
    assert 'grep -qxF "module.mam.$recurso[\\"nao_identificadas\\"]"' in antes
    assert (
        'tf state mv "module.mam.$recurso[\\"nao_identificadas\\"]" "module.mam.$recurso"'
        in antes
    )


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


def test_o_ci_confere_o_formato_de_todo_o_infra_de_uma_vez() -> None:
    ci = (RAIZ / ".github" / "workflows" / "ci.yml").read_text()

    assert "terraform -chdir=infra fmt -check -recursive" in ci
    assert "ambientes/prod fmt" not in ci


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
    lista_do_readme = re.search(
        r"^A `mam-terraform` recebe do wizard.*?\n\n((?:- `roles/[\w.]+`\n)+)",
        readme,
        re.DOTALL | re.MULTILINE,
    )
    assert lista_do_readme
    assert set(re.findall(r"`(roles/[\w.]+)`", lista_do_readme.group(1))) == set(papeis)
    for papel in re.findall(
        r'role\s*= "(roles/[\w.]+)"\n\s*member\s*= google_service_account\.mam\["build"\]',
        (MODULO / "main.tf").read_text(),
    ) + ["roles/logging.logWriter"]:
        assert f"`{papel}`" in readme, papel


# --- A coleção da busca criada pelo deploy (#757) ---

CRIAR = RAIZ / "scripts" / "criar-colecao-no-deploy.sh"
SAIDAS_DA_BUSCA = {
    "busca_regiao": "us-east4",
    "busca_colecao": "momentos",
    "busca_colecao_de_texto": "texto",
    "busca_indice_descricao": "indice",
    "busca_dimensao": 256,
    "busca_indices_ligados": False,
}


def test_o_deploy_cria_a_colecao_da_busca_depois_do_apply_direcionado_e_antes_do_build() -> (
    None
):
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()
    apply = deploy.index("scripts/aplicar-sem-destruir.sh -target=module.mam.")
    criar = deploy.index("scripts/criar-colecao-no-deploy.sh")
    build = deploy.index("gc builds submit")

    assert apply < criar < build
    assert (
        "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT=$GOOGLE_IMPERSONATE_SERVICE_ACCOUNT"
        in deploy[criar - 200 : criar]
    )


def test_o_papel_da_busca_da_mam_terraform_esta_no_modulo_e_no_primeiro_apply() -> None:
    papel = (MODULO / "papel_vertex.tf").read_text()
    bloco = papel[
        papel.index('resource "google_project_iam_member" "terraform_busca"') :
    ]
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()
    primeiro = deploy[
        deploy.index("scripts/aplicar-sem-destruir.sh -target=module.mam.") :
    ].split("-var imagem=pendente")[0]

    # Papel sob medida: só o que api.criar_colecao_da_busca chama, nada de apagar.
    assert set(re.findall(r'"(vectorsearch\.[\w.]+)"', papel)) == {
        "vectorsearch.collections.create",
        "vectorsearch.collections.get",
        "vectorsearch.collections.update",
        "vectorsearch.indexes.create",
        "vectorsearch.indexes.get",
        "vectorsearch.operations.get",
    }
    assert "role    = google_project_iam_custom_role.busca_no_deploy.id" in bloco
    assert "local.conta_do_terraform" in bloco
    assert "-target=module.mam.google_project_iam_member.terraform_busca" in primeiro
    assert "terraform_predicao_vertex" in primeiro


def _criar(
    tmp_path: Path,
    saidas: dict[str, object],
    saida_do_python: str = "Coleções e índice da busca prontos.",
    codigo: int = 0,
    **ambiente: str,
) -> subprocess.CompletedProcess[str]:
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (tmp_path / "saida.json").write_text(
        json.dumps({k: {"value": v, "type": "x"} for k, v in saidas.items()})
    )
    (tmp_path / "saida_do_python").write_text(saida_do_python + "\n")
    (bin_ / "terraform").write_text(f"#!/bin/sh\ncat {tmp_path}/saida.json\n")
    (bin_ / "uv").write_text(
        "#!/bin/sh\n"
        f"env | grep '^BUSCA_' | sort > {tmp_path}/busca\n"
        f'echo "$@" > {tmp_path}/argumentos\n'
        f"cat {tmp_path}/saida_do_python\nexit {codigo}\n"
    )
    for f in ("terraform", "uv"):
        (bin_ / f).chmod(0o755)
    limpo = {k: v for k, v in os.environ.items() if not k.startswith("BUSCA_")}
    return subprocess.run(
        [str(CRIAR)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **limpo,
            "PATH": f"{bin_}:{os.environ['PATH']}",
            "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": CONTA_DO_DEPLOY,
            **ambiente,
        },
    )


CONTA_DO_DEPLOY = "mam-terraform@proj-x.iam.gserviceaccount.com"


def test_o_deploy_pede_a_impersonacao_de_forma_explicita(tmp_path: Path) -> None:
    feito = _criar(tmp_path, SAIDAS_DA_BUSCA)

    assert feito.returncode == 0, feito.stderr
    argumentos = (tmp_path / "argumentos").read_text()
    assert "api.criar_colecao_da_busca" in argumentos
    assert f"--personificar {CONTA_DO_DEPLOY}" in argumentos


def test_o_aviso_de_reindexar_sai_mesmo_se_a_criacao_falha_depois_do_patch(
    tmp_path: Path,
) -> None:
    resumo = tmp_path / "resumo"
    feito = _criar(
        tmp_path,
        SAIDAS_DA_BUSCA,
        "Campos acrescentados ao esquema: x. Rode `make reindexar`.\n429 cota",
        codigo=1,
        GITHUB_STEP_SUMMARY=str(resumo),
    )

    assert feito.returncode == 1
    assert "make reindexar" in resumo.read_text()
    assert "rode o deploy de novo" in feito.stderr


def test_os_outputs_que_a_criacao_le_existem_depois_do_apply_direcionado() -> None:
    """Num apply com -target, o Terraform só grava o output com dependência no alvo: sem ela,
    os outputs feitos só de locals não existiriam num estado novo e a criação pararia o deploy."""
    modulo = (MODULO / "main.tf").read_text()
    for saida in SAIDAS_DA_BUSCA:
        bloco = modulo[modulo.index(f'output "{saida}" {{') :].split("\n}")[0]
        assert "depends_on = [google_project_iam_member.terraform_busca]" in bloco, (
            saida
        )


def test_o_erro_de_esquema_incompativel_nao_vira_aviso_de_reindexar(
    tmp_path: Path,
) -> None:
    # A orientação do erro (api/agent_retrieval.py) cita `make reindexar` sem PATCH feito.
    resumo = tmp_path / "resumo"
    feito = _criar(
        tmp_path,
        SAIDAS_DA_BUSCA,
        "esquema incompatível: rode `make criar-colecao-da-busca` e `make reindexar`",
        codigo=1,
        GITHUB_STEP_SUMMARY=str(resumo),
    )

    assert feito.returncode == 1
    assert not resumo.exists() or "ganhou campos" not in resumo.read_text()


def test_a_chamada_no_deploy_nao_engole_a_falha() -> None:
    # O `set -e` do deploy faz o resto: a linha não pode ter `||`, `!` nem `if`.
    linhas = (RAIZ / "scripts" / "deploy-dev.sh").read_text().splitlines()
    i = next(
        n
        for n, l in enumerate(linhas)
        if "scripts/criar-colecao-no-deploy.sh" in l and not l.lstrip().startswith("#")
    )
    chamada = " ".join(linhas[i - 1 : i + 1])
    assert "||" not in chamada and "!" not in chamada and "if " not in chamada
    assert not linhas[i].rstrip().endswith("\\")


def _busca(tmp_path: Path) -> dict[str, str]:
    linhas = (tmp_path / "busca").read_text().splitlines()
    return dict(linha.split("=", 1) for linha in linhas)


def test_a_criacao_recebe_so_os_seis_valores_do_terraform(tmp_path: Path) -> None:
    # O ambiente local traz o índice ligado e uma cota inválida; nenhum dos dois chega ao Python.
    feito = _criar(
        tmp_path,
        SAIDAS_DA_BUSCA,
        BUSCA_INDICES_LIGADOS="true",
        BUSCA_COTA_DE_ESCRITA="abc",
        BUSCA_DISTANCIA_MAXIMA="x",
    )

    assert feito.returncode == 0, feito.stderr
    assert _busca(tmp_path) == {
        "BUSCA_REGIAO": "us-east4",
        "BUSCA_COLECAO": "momentos",
        "BUSCA_COLECAO_DE_TEXTO": "texto",
        "BUSCA_INDICE_DESCRICAO": "indice",
        "BUSCA_DIMENSAO": "256",
        "BUSCA_INDICES_LIGADOS": "false",
    }


def test_o_indice_ligado_do_terraform_chega_como_true(tmp_path: Path) -> None:
    feito = _criar(tmp_path, {**SAIDAS_DA_BUSCA, "busca_indices_ligados": True})

    assert feito.returncode == 0, feito.stderr
    assert _busca(tmp_path)["BUSCA_INDICES_LIGADOS"] == "true"


@pytest.mark.parametrize("faltando", list(SAIDAS_DA_BUSCA))
def test_output_da_busca_ausente_aborta_antes_de_criar(
    tmp_path: Path, faltando: str
) -> None:
    saidas = {k: v for k, v in SAIDAS_DA_BUSCA.items() if k != faltando}

    feito = _criar(tmp_path, saidas)

    assert feito.returncode == 1
    assert faltando in feito.stderr
    assert not (tmp_path / "busca").exists()


def test_a_falha_da_criacao_para_o_deploy_com_saida_1_e_diz_como_seguir(
    tmp_path: Path,
) -> None:
    feito = _criar(tmp_path, SAIDAS_DA_BUSCA, "403 sem permissão", codigo=3)

    assert feito.returncode == 1
    assert "403 sem permissão" in feito.stdout
    assert "rode o deploy de novo" in feito.stderr


def test_o_aviso_de_reindexar_e_repassado(tmp_path: Path) -> None:
    resumo = tmp_path / "resumo"
    feito = _criar(
        tmp_path,
        SAIDAS_DA_BUSCA,
        "Campos acrescentados ao esquema: x. Rode `make reindexar`.",
        GITHUB_STEP_SUMMARY=str(resumo),
    )

    assert feito.returncode == 0
    assert "make reindexar" in feito.stderr
    assert "make reindexar" in resumo.read_text()
