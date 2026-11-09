"""Imagem, build e publicação do Job de objetos com GPU (Florence-2, #243), sem nuvem."""

import re
from pathlib import Path

import pytest

from api import florence

RAIZ = Path(__file__).parents[2]
DOCKERFILE = (RAIZ / "Dockerfile").read_text()
ALVO = DOCKERFILE[DOCKERFILE.index("AS objetos-gpu") :].split("\nFROM ")[0]

# (SHA-256, arquivo) de cada arquivo do modelo na revisão fixada.
ARQUIVOS_DO_MODELO = [
    (
        "8412483f687f2f71587328a38c6fa70a68d9488f28e90607be3c182641f60f2c",
        "config.json",
    ),
    (
        "0251459c49cc358ac033b5d4b8569e61ac22bde5d76be404b97a44cfb33fb12e",
        "generation_config.json",
    ),
    (
        "7715423d6549bf1e71188bdd84f4ac960cc0597886af24a5ef7b66f128660685",
        "model.safetensors",
    ),
    (
        "1396ec5a0a7adfe1c04fb777b09e8ba753be6dbb5868212ab3c3ef39d91fe031",
        "preprocessor_config.json",
    ),
    (
        "cd0e3bf41a39b1276503fbd273bc03b9afc70d7a15ea681a92a1b4b77f858ee6",
        "processor_config.json",
    ),
    (
        "3ad7001f773409abe6bba33eac92662611a73d72f459bda2f00d2a221dd31ce4",
        "tokenizer.json",
    ),
    (
        "cb5f80bd9afa767bb1bb798ee5f0a79eae45239b8e72506166b4218175a16723",
        "tokenizer_config.json",
    ),
    (
        "1d75deda84dfa81fb6c09301f3fed00f9695059568bbb1403a6bf299cd84fc37",
        "added_tokens.json",
    ),
    (
        "1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5",
        "merges.txt",
    ),
    (
        "72ff172dc769bc1551b1b4211628ce3271643bc60379e4da45d85a9be9332c39",
        "special_tokens_map.json",
    ),
    (
        "ed19656ea1707df69134c4af35c8ceda2cc9860bf2c3495026153a133670ab5e",
        "vocab.json",
    ),
]
HASH_DA_AMOSTRA = "8cd28b372908bcaa704a438965f8de47238c9514d5efefa89c510b82032f9d18"


def test_o_alvo_baixa_o_modelo_na_revisao_do_adaptador_conferindo_cada_hash() -> None:
    hashes_especificos = {
        "large": [ARQUIVOS_DO_MODELO[0][0], ARQUIVOS_DO_MODELO[2][0]],
        "base": [
            "2a4dfe9885d183da121f239ada734bd700ee6908b650a7a25ab32eb104fe1d7a",
            "62f3e696da74f8869a68ddb529a9b3e14eb25b21c592cb3dea6179bf944df6a0",
        ],
    }
    for nome, modelo in florence.MODELOS.items():
        repositorio, revisao = modelo.split("@")
        assert (
            f'"{nome} {repositorio} {revisao} {" ".join(hashes_especificos[nome])}"'
            in ALVO
        )
    assert "huggingface.co/$MODELO/resolve/$MODELO_REVISAO/$arquivo" in ALVO
    assert '"/modelo/$nome/$arquivo"' in ALVO
    assert len(ARQUIVOS_DO_MODELO) == 11
    for hash_, arquivo in ARQUIVOS_DO_MODELO:
        if arquivo not in ("config.json", "model.safetensors"):
            assert f"{hash_}  /modelo/$nome/{arquivo}" in ALVO
    assert "$4  /modelo/$nome/config.json" in ALVO
    assert "$5  /modelo/$nome/model.safetensors" in ALVO
    assert "sha256sum -c /tmp/hashes || exit 1;" in ALVO


def test_o_alvo_baixa_a_amostra_conferindo_o_hash_antes_do_uv_sync() -> None:
    assert "/amostras/objetos.jpg" in ALVO
    assert f"{HASH_DA_AMOSTRA}  /amostras/objetos.jpg" in ALVO
    assert "9dd8e4710f6b2ddf5184d308639e0359bc7b55be" in ALVO
    assert ALVO.index("/amostras/objetos.jpg") < ALVO.index("RUN uv sync")
    assert ALVO.index("resolve/$MODELO_REVISAO") < ALVO.index("RUN uv sync")


def test_o_alvo_instala_o_grupo_objetos_e_confere_em_cpu_antes_do_usuario() -> None:
    assert "uv sync --locked --no-dev --group objetos" in ALVO
    conferencia = "testar_objetos('cpu', exigir_gpu=False)"
    assert "RUN FLORENCE_MODELO=large " in ALVO
    assert conferencia in ALVO
    assert ALVO.index(conferencia) < ALVO.index("USER nobody")
    assert ALVO.index("COPY api/__init__.py") < ALVO.index(conferencia)


def test_o_alvo_roda_offline_com_gpu_e_sem_codigo_remoto() -> None:
    for ambiente in (
        "HF_HUB_OFFLINE=1",
        "TRANSFORMERS_OFFLINE=1",
        "HOME=/saida",
        "TMPDIR=/saida",
        "PASTA_DO_MODELO=/modelo",
        "AMOSTRAS=/amostras",
        "LD_LIBRARY_PATH=/usr/local/nvidia/lib64",
        "DISPOSITIVO=gpu",
    ):
        assert ambiente in ALVO
    assert 'CMD ["python", "-m", "api.objetos_job"]' in ALVO
    assert "trust_remote_code" not in ALVO


def test_o_bake_monta_e_envia_a_imagem_com_cache_da_gpu() -> None:
    bake = (RAIZ / "docker-bake.hcl").read_text()
    cloudbuild = (RAIZ / "cloudbuild.yaml").read_text()
    padrao = bake[bake.index('group "default"') :].split("}")[0]
    gpu = bake[bake.index('group "gpu"') :].split("}")[0]
    bloco = bake[bake.index('target "objetos-gpu"') :].split("\n}")[0]

    assert 'variable "OBJETOS_GPU" {}' in bake
    assert "objetos-gpu" in padrao and "objetos-gpu" in gpu
    assert 'inherits   = ["base"]' in bloco
    assert "tags       = [OBJETOS_GPU]" in bloco
    assert "type=registry,ref=${CACHE_GPU}:objetos-gpu" in bloco
    assert "mode=max" in bloco
    assert "OBJETOS_GPU=$_OBJETOS_GPU" in cloudbuild


def test_o_cloud_build_cobre_a_imagem_do_florence_com_a_estimativa() -> None:
    cloudbuild = (RAIZ / "cloudbuild.yaml").read_text()

    timeout = re.search(r"^timeout: (\d+)s", cloudbuild, re.MULTILINE)
    assert timeout and int(timeout.group(1)) >= 5400
    assert "objetos-gpu" in cloudbuild.split("timeout:")[0]


MAIN = (RAIZ / "infra" / "modulos" / "mam" / "main.tf").read_text()


def _bloco(cabecalho: str) -> str:
    return MAIN[MAIN.index(cabecalho) :].split("\nresource ")[0].split("\nvariable ")[0]


def test_a_conta_do_job_so_toca_o_bucket_das_decupagens() -> None:
    assert '"objetos"' in MAIN.split('resource "google_service_account" "mam"')[1][:400]
    papeis = MAIN[MAIN.index("papeis_nos_buckets = {") :]
    linha = re.search(r"^\s+objetos = \{(.*)\}$", papeis, re.MULTILINE)
    assert linha
    assert linha.group(1).strip() == 'decupagens = "roles/storage.objectUser"'
    # O comentário diz o que a conta faz com o bucket.
    assert "# Lê a Decupagem e os quadros e grava o resultado" in papeis
    # No projeto, só a Vertex (o Job do inventário chama o Gemini): sem Firestore.
    projeto = MAIN[
        MAIN.index("papeis_no_projeto = {") : MAIN.index("papeis_nos_buckets")
    ]
    linha_do_projeto = re.search(r"^\s+objetos\s+= \[(.*)\]$", projeto, re.MULTILINE)
    assert linha_do_projeto
    assert linha_do_projeto.group(1) == "local.papel_vertex_predicao"


def test_o_job_de_objetos_tem_uma_l4_4_cpus_16_gib_e_a_rede_da_gpu() -> None:
    job = _bloco('resource "google_cloud_run_v2_job" "objetos_gpu"')

    assert 'name                = "mam-objetos-gpu"' in job
    assert "location            = var.regiao_gpu" in job
    assert 'accelerator = "nvidia-l4"' in job
    assert '"nvidia.com/gpu" = "1"' in job
    assert re.search(r'cpu\s+= "4"', job) and re.search(r'memory\s+= "16Gi"', job)
    assert "gpu_zonal_redundancy_disabled = true" in job
    assert 'egress = "ALL_TRAFFIC"' in job
    assert "google_compute_subnetwork.validacao_gpu.id" in job
    assert 'google_service_account.mam["objetos"]' in job
    assert "image = var.imagem_objetos\n" in job
    assert "max_retries     = 0" in job
    assert re.search(r'timeout\s+= "10800s"', job)
    assert re.search(r'name\s+= "GCP_PROJECT_ID"\s+value = var.projeto', job)
    assert re.search(
        r'name\s+= "BUCKET_DECUPAGENS"\s+value = local.buckets\["decupagens"\]', job
    )
    assert "BUCKET_ACEITOS" not in job
    assert re.search(r'name\s+= "TMPDIR"\s+value = "/saida"', job)
    assert re.search(r'name\s+= "DISPOSITIVO"\s+value = "gpu"', job)
    assert re.search(r'medium\s+= "MEMORY"', job) and 'size_limit = "2Gi"' in job
    assert "us-east4" not in job


def test_o_timeout_do_job_de_objetos_tem_a_conta_no_comentario() -> None:
    job = _bloco('resource "google_cloud_run_v2_job" "objetos_gpu"')

    assert "2000 quadros" in job and "1,75" in job


def test_a_orquestracao_roda_o_job_de_objetos() -> None:
    iam = _bloco(
        'resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_objetos_gpu"'
    )

    assert "google_cloud_run_v2_job.objetos_gpu.name" in iam
    assert 'role     = "roles/run.developer"' in iam
    assert 'google_service_account.mam["orquestracao"]' in iam


def test_o_motor_dos_objetos_e_florence_por_padrao_e_so_aceita_dois_valores() -> None:
    variavel = _bloco('variable "motor_objetos"')

    assert 'default     = "florence"' in variavel or 'default = "florence"' in variavel
    assert '"florence"' in variavel and '"gemini"' in variavel
    assert "contains(" in variavel


def test_o_workflows_recebe_o_motor_e_o_job_de_objetos_e_o_cabecalho_os_cita() -> None:
    assert re.search(r"motor_objetos\s+= var\.motor_objetos", MAIN)
    assert re.search(
        r"job_de_objetos_gpu\s+= google_cloud_run_v2_job\.objetos_gpu\.name", MAIN
    )
    cabecalho = (
        (RAIZ / "infra" / "modulos" / "mam" / "validacao.workflow.yaml")
        .read_text()
        .split("\nmain:")[0]
    )
    assert "${motor_objetos}" in cabecalho and "${job_de_objetos_gpu}" in cabecalho


def test_a_imagem_e_o_nome_do_job_saem_como_output() -> None:
    assert "google_cloud_run_v2_job.objetos_gpu.name" in _bloco(
        'output "job_de_objetos_gpu"'
    )
    assert 'variable "imagem_objetos"' in MAIN


def test_deploy_dev_publica_e_testa_o_job_de_objetos_pelo_digest() -> None:
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()

    primeiro = deploy[: deploy.index("REPOSITORIO=$(")]
    assert "-var imagem_objetos=pendente" in primeiro
    assert 'OBJETOS_GPU="$REPOSITORIO_GPU/objetos-gpu:$COMMIT"' in deploy
    assert "OBJETOS_GPU_ANTES=$(imagem_do_job objetos_gpu job_de_objetos_gpu)" in deploy
    assert "_OBJETOS_GPU=$OBJETOS_GPU" in deploy
    assert 'IMAGEM_OBJETOS=$(digest "$OBJETOS_GPU")' in deploy
    assert '-var "imagem_objetos=$IMAGEM_OBJETOS"' in deploy
    assert "job_de_objetos_gpu),$OBJETOS_GPU_ANTES,$IMAGEM_OBJETOS" in deploy
    assert "as cinco imagens" in deploy


def test_o_job_do_inventario_roda_em_cpu_sem_internet_com_o_motor_e_o_modelo() -> None:
    job = _bloco('resource "google_cloud_run_v2_job" "inventario"')

    assert 'name                = "mam-inventario"' in job
    assert "location            = var.regiao" in job
    assert 'google_service_account.mam["objetos"].email' in job
    assert "image   = var.imagem_validacao" in job
    assert 'args    = ["-m", "api.inventario_job"]' in job
    assert "nvidia" not in job
    assert 'egress = "ALL_TRAFFIC"' in job
    assert "google_compute_subnetwork.validacao.id" in job
    assert 'value = local.buckets["decupagens"]' in job
    assert "value = var.motor_objetos" in job
    assert "value = var.modelo_objetos" in job
    assert "max_retries     = 0" in job


def test_o_modelo_do_inventario_e_o_flash_lite_do_gemini() -> None:
    from api.gemini import MODELO

    assert f'default     = "{MODELO}"' in _bloco('variable "modelo_objetos"')


def test_a_orquestracao_roda_o_job_do_inventario_e_o_workflows_o_recebe() -> None:
    iam = _bloco(
        'resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_inventario"'
    )
    assert "google_cloud_run_v2_job.inventario.name" in iam
    assert 'role     = "roles/run.developer"' in iam
    assert re.search(
        r"job_de_inventario\s+= google_cloud_run_v2_job\.inventario\.name", MAIN
    )
    assert "google_cloud_run_v2_job.inventario.name" in _bloco(
        'output "job_de_inventario"'
    )


@pytest.mark.parametrize("raiz", ["infra", "infra/ambientes/prod"])
def test_as_quatro_variaveis_do_florence_chegam_ao_job_com_os_padroes(
    raiz: str,
) -> None:
    modulo = RAIZ / "infra/modulos/mam"
    job = _bloco('resource "google_cloud_run_v2_job" "objetos_gpu"')
    chamada = (
        (RAIZ / raiz / "main.tf").read_text().split('module "mam"')[1].split("\n}")[0]
    )
    for nome, padrao, expressao in (
        ("modelo", '"base"', "var.florence_modelo"),
        ("feixes", "1", "tostring(var.florence_feixes)"),
        ("lote", "16", "tostring(var.florence_lote)"),
        ("legendas", "1", "tostring(var.florence_legendas)"),
    ):
        variavel = f"florence_{nome}"
        for pasta in (RAIZ / raiz, modulo):
            texto = (pasta / "variables.tf").read_text()
            bloco = texto.split(f'variable "{variavel}"')[1].split("\n}")[0]
            assert re.search(rf"default\s*= {re.escape(padrao)}\n", bloco)
            assert "validation {" in bloco
        assert re.search(rf"{variavel}\s*= var\.{variavel}\n", chamada)
        assert re.search(
            rf'name\s*= "FLORENCE_{nome.upper()}"\s+value\s*= {re.escape(expressao)}\n',
            job,
        )


@pytest.mark.parametrize("raiz", ["infra", "infra/ambientes/prod"])
def test_a_escolha_large_na_raiz_e_repassada_sem_fixar_base_no_job(raiz: str) -> None:
    chamada = (
        (RAIZ / raiz / "main.tf").read_text().split('module "mam"')[1].split("\n}")[0]
    )
    job = _bloco('resource "google_cloud_run_v2_job" "objetos_gpu"')
    assert re.search(r"florence_modelo\s*= var\.florence_modelo\n", chamada)
    assert re.search(r'name\s*= "FLORENCE_MODELO"\s+value = var\.florence_modelo', job)
    for pasta in (RAIZ / raiz, RAIZ / "infra/modulos/mam"):
        assert (
            'contains(["base", "large"], var.florence_modelo)'
            in (pasta / "variables.tf").read_text()
        )
