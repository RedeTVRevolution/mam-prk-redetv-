"""Infraestrutura dos Jobs com GPU (#238): Terraform, build e publicação, sem nuvem."""

import json
import re
import shlex
import subprocess
from pathlib import Path

RAIZ = Path(__file__).parents[2]
MAIN = (RAIZ / "infra" / "modulos" / "mam" / "main.tf").read_text()


def _bloco(cabecalho: str) -> str:
    return MAIN[MAIN.index(cabecalho) :].split("\nresource ")[0].split("\nvariable ")[0]


def test_a_regiao_da_gpu_vem_de_uma_variavel_com_us_east4_como_padrao() -> None:
    variavel = _bloco('variable "regiao_gpu"')

    assert 'default = "us-east4"' in variavel
    # Nenhum recurso da GPU escreve a região: tudo passa pela variável.
    gpu = (
        _bloco('resource "google_compute_subnetwork" "validacao_gpu"')
        + _bloco('resource "google_artifact_registry_repository" "mam_gpu"')
        + _bloco('resource "google_cloud_run_v2_job" "transcricao_gpu"')
        + _bloco('resource "google_cloud_run_v2_job" "ocr_gpu"')
        + _bloco('resource "google_cloud_run_v2_job" "objetos_gpu"')
    )
    assert "us-east4" not in gpu
    assert gpu.count("var.regiao_gpu") == 5


def test_sub_rede_da_gpu_na_rede_que_ja_existe_sem_nat_e_sem_sobrepor_a_faixa() -> None:
    sub = _bloco('resource "google_compute_subnetwork" "validacao_gpu"')

    assert "google_compute_network.validacao.id" in sub
    assert "private_ip_google_access = true" in sub
    assert 'ip_cidr_range            = "10.20.0.0/24"' in sub
    assert '"10.10.0.0/24"' in _bloco(
        'resource "google_compute_subnetwork" "validacao"'
    )
    assert "google_compute_router" not in MAIN and "external_ip" not in MAIN


def test_o_repositorio_da_gpu_tem_a_permissao_da_mam_build_pelo_terraform() -> None:
    iam = _bloco(
        'resource "google_artifact_registry_repository_iam_member" "build_envia_gpu"'
    )

    assert "google_artifact_registry_repository.mam_gpu" in iam
    assert 'role       = "roles/artifactregistry.writer"' in iam
    assert 'google_service_account.mam["build"]' in iam


import pytest


@pytest.mark.parametrize(
    ("nome", "conta", "imagem", "timeout"),
    [
        ("transcricao_gpu", "transcricao", "var.imagem_transcricao_gpu", "10800s"),
        ("ocr_gpu", "ocr", "var.imagem_ocr_gpu", "21600s"),
    ],
)
def test_job_com_gpu_tem_uma_l4_4_cpus_16_gib_e_a_rede_da_gpu(
    nome: str, conta: str, imagem: str, timeout: str
) -> None:
    job = _bloco(f'resource "google_cloud_run_v2_job" "{nome}"')

    assert 'accelerator = "nvidia-l4"' in job
    assert '"nvidia.com/gpu" = "1"' in job
    assert re.search(r'cpu\s+= "4"', job) and re.search(r'memory\s+= "16Gi"', job)
    assert "gpu_zonal_redundancy_disabled = true" in job
    assert 'egress = "ALL_TRAFFIC"' in job
    assert "google_compute_subnetwork.validacao_gpu.id" in job
    assert "google_compute_subnetwork.validacao.id" not in job
    assert f'google_service_account.mam["{conta}"]' in job
    assert imagem in job
    assert re.search(rf'timeout\s+= "{timeout}"', job)
    assert "max_retries     = 0" in job
    assert 'local.buckets["aceitos"]' in job and "var.projeto" in job
    assert re.search(r'name\s+= "DISPOSITIVO"\s+value = "gpu"', job)
    assert re.search(r'name\s+= "TMPDIR"\s+value = "/saida"', job)
    assert (
        'google_storage_bucket" ' not in job
        and 'resource "google_storage_bucket"' not in job
    )


def test_o_volume_do_ocr_com_gpu_e_a_memoria_dele_cabem_nos_16_gib() -> None:
    job = _bloco('resource "google_cloud_run_v2_job" "ocr_gpu"')

    # O volume em memória conta na memória: 8 GiB de volume e sobram 8 para o Paddle.
    assert 'size_limit = "8Gi"' in job and 'medium     = "MEMORY"' in job


def test_orquestracao_roda_os_dois_jobs_com_gpu() -> None:
    for nome in ("transcricao_gpu", "ocr_gpu"):
        iam = _bloco(
            f'resource "google_cloud_run_v2_job_iam_member" "orquestracao_roda_{nome}"'
        )
        assert f"google_cloud_run_v2_job.{nome}.name" in iam
        assert 'role     = "roles/run.developer"' in iam
        assert 'google_service_account.mam["orquestracao"]' in iam


def test_os_jobs_em_cpu_continuam_como_estavam() -> None:
    for nome, imagem in (("transcricao", "imagem_transcricao"), ("ocr", "imagem_ocr")):
        job = _bloco(f'resource "google_cloud_run_v2_job" "{nome}"')
        assert "location            = var.regiao\n" in job
        assert f"image = var.{imagem}\n" in job
        assert "google_compute_subnetwork.validacao.id" in job
        assert 'cpu    = "8"' in job
        assert "nvidia" not in job and "gpu" not in job.replace("regiao_gpu", "")


def test_nenhum_bucket_nasce_na_regiao_da_gpu() -> None:
    assert "regiao_gpu" not in _bloco('resource "google_storage_bucket" "mam"')


def test_saidas_para_o_workflows_e_para_o_teste_depois_da_publicacao() -> None:
    for saida, valor in [
        ("regiao_gpu", "var.regiao_gpu"),
        ("job_de_transcricao_gpu", "google_cloud_run_v2_job.transcricao_gpu.name"),
        ("job_de_ocr_gpu", "google_cloud_run_v2_job.ocr_gpu.name"),
        ("job_de_objetos_gpu", "google_cloud_run_v2_job.objetos_gpu.name"),
        ("gpu_espera_total_s", "var.espera_gpu_minutos * 60"),
        ("gpu_espera_maxima_s", "var.gpu_espera_maxima_s"),
        ("gpu_espera_s", "var.gpu_espera_s"),
        ("gpu_fator_da_espera", "var.gpu_fator_da_espera"),
        ("repositorio_gpu", "google_artifact_registry_repository.mam_gpu"),
    ]:
        assert valor in _bloco(f'output "{saida}"')
    # O templatefile do Workflows recebe a região e os nomes (o #239 os usa).
    assert re.search(r"regiao_gpu\s+= var\.regiao_gpu", MAIN)
    assert re.search(
        r"job_de_transcricao_gpu\s+= google_cloud_run_v2_job\.transcricao_gpu\.name",
        MAIN,
    )
    assert re.search(r"job_de_ocr_gpu\s+= google_cloud_run_v2_job\.ocr_gpu\.name", MAIN)


def test_a_espera_por_falta_de_gpu_tem_15_minutos_e_esperas_de_1_a_4_minutos() -> None:
    assert re.search(r"default\s+= 15", _bloco('variable "espera_gpu_minutos"'))
    assert re.search(r"default\s+= 60", _bloco('variable "gpu_espera_s"'))
    assert re.search(r"default\s+= 2", _bloco('variable "gpu_fator_da_espera"'))
    assert re.search(r"default\s+= 240", _bloco('variable "gpu_espera_maxima_s"'))
    assert 'variable "gpu_tentativas"' not in MAIN


def test_o_bake_e_o_cloud_build_montam_e_enviam_as_duas_imagens_com_cache() -> None:
    bake = (RAIZ / "docker-bake.hcl").read_text()
    padrao = bake[bake.index('group "default"') :].split("}")[0]
    cloudbuild = (RAIZ / "cloudbuild.yaml").read_text()

    assert "transcricao-gpu" in padrao and "ocr-gpu" in padrao
    for alvo, imagem in (
        ("transcricao-gpu", "TRANSCRICAO_GPU"),
        ("ocr-gpu", "OCR_GPU"),
    ):
        bloco = bake[bake.index(f'target "{alvo}"') :].split("\n}")[0]
        assert 'inherits   = ["base"]' in bloco  # envia pelo registry
        assert f"tags       = [{imagem}]" in bloco
        assert f"type=registry,ref=${{CACHE_GPU}}:{alvo}" in bloco
        assert "cache-to" in bloco and "mode=max" in bloco
        assert f"{imagem}=$_{imagem}" in cloudbuild
    assert "CACHE_GPU=$_CACHE_GPU" in cloudbuild


def test_timeout_e_disco_do_cloud_build_cobrem_a_primeira_montagem_sem_cache() -> None:
    cloudbuild = (RAIZ / "cloudbuild.yaml").read_text()

    # Mais que os 1800 s e os 200 GB de antes das duas imagens com CUDA e Paddle.
    timeout = re.search(r"^timeout: (\d+)s", cloudbuild, re.MULTILINE)
    disco = re.search(r"diskSizeGb: (\d+)", cloudbuild)
    assert timeout and int(timeout.group(1)) >= 3600
    assert disco and int(disco.group(1)) >= 300
    assert "ESTIMADA" in cloudbuild


def test_deploy_dev_cria_o_repositorio_novo_no_primeiro_apply_e_publica_pelos_digests() -> (
    None
):
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()

    primeiro = deploy[: deploy.index("REPOSITORIO=$(")]
    assert "-target=module.mam.google_artifact_registry_repository.mam_gpu" in primeiro
    assert (
        "-target=module.mam.google_artifact_registry_repository_iam_member.build_envia_gpu"
        in primeiro
    )
    assert (
        "-var imagem_transcricao_gpu=pendente -var imagem_ocr_gpu=pendente" in primeiro
    )
    assert (
        "_TRANSCRICAO_GPU=$TRANSCRICAO_GPU,_OCR_GPU=$OCR_GPU,_OBJETOS_GPU=$OBJETOS_GPU,_CACHE_GPU=$CACHE_GPU"
        in deploy
    )
    assert 'digest "$TRANSCRICAO_GPU"' in deploy and 'digest "$OCR_GPU"' in deploy
    assert '-var "imagem_transcricao_gpu=$IMAGEM_TRANSCRICAO_GPU"' in deploy
    assert '-var "imagem_ocr_gpu=$IMAGEM_OCR_GPU"' in deploy


def test_deploy_dev_le_as_imagens_antes_do_apply_e_testa_depois_so_os_jobs_com_gpu() -> (
    None
):
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()

    antes = deploy.index("TRANSCRICAO_GPU_ANTES=$(")
    cloudbuild = deploy.index("gc builds submit")
    apply = deploy.index('scripts/aplicar-sem-destruir.sh -var "imagem=$IMAGEM"')
    teste = deploy.index("scripts/testar-jobs-gpu.sh")
    assert antes < cloudbuild < apply < teste
    assert (
        "job_de_transcricao_gpu),$TRANSCRICAO_GPU_ANTES,$IMAGEM_TRANSCRICAO_GPU"
        in deploy
    )
    assert "job_de_ocr_gpu),$OCR_GPU_ANTES,$IMAGEM_OCR_GPU" in deploy
    # As esperas são as do Terraform, as mesmas do Workflows.
    for saida in (
        "gpu_espera_total_s",
        "gpu_espera_s",
        "gpu_fator_da_espera",
        "gpu_espera_maxima_s",
        "regiao_gpu",
    ):
        assert f"tf output -raw {saida}" in deploy[teste - 600 :]
    assert deploy.index("URL=$(tf output") > teste


def test_o_limiar_de_mudanca_do_ocr_vem_de_uma_variavel_nos_dois_jobs() -> None:
    variavel = _bloco('variable "limiar_de_mudanca_do_ocr"')

    assert "default     = 3" in variavel
    for nome in ("ocr", "ocr_gpu"):
        job = _bloco(f'resource "google_cloud_run_v2_job" "{nome}"')
        assert "LIMIAR_DE_MUDANCA" in job
        assert "tostring(var.limiar_de_mudanca_do_ocr)" in job


@pytest.mark.parametrize("nome", ["transcricao_gpu", "ocr_gpu", "objetos_gpu"])
def test_job_com_gpu_de_mais_de_uma_hora_declara_beta(nome: str) -> None:
    # Sem BETA, a API recusa GPU com timeout acima de 1 h (deploy de 2026-11-03).
    job = _bloco(f'resource "google_cloud_run_v2_job" "{nome}"')
    assert 'launch_stage = "BETA"' in job


def _funcao_do_deploy(nome: str) -> str:
    """Recorta do deploy-dev.sh a definição da função `nome`."""
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()
    inicio = deploy.index(f"{nome}() {{")
    return deploy[inicio : deploy.index("\n}\n", inicio) + 3]


def _rodar_imagem_do_job(estado: str, describe_falha: bool = False) -> tuple[int, str]:
    """Roda a imagem_do_job do deploy-dev.sh com tf e gc simulados."""
    funcao = _funcao_do_deploy("imagem_do_job")
    script = f"""set -euo pipefail
tf() {{ [[ $* == "output -raw job_de_ocr_gpu" ]] && echo mam-ocr-gpu; }}
gc() {{ {"echo 'Cannot find job' >&2; return 1" if describe_falha else 'echo "imagem-de-$4"'}; }}
GPU_REGIAO=us-east4
ESTADO_DOS_JOBS={shlex.quote(estado)}
{funcao}
ANTES=$(imagem_do_job ocr_gpu job_de_ocr_gpu)
echo "[$ANTES]"
"""
    feito = subprocess.run(
        ["bash", "-c", script], check=False, capture_output=True, text=True
    )
    return feito.returncode, feito.stdout.strip()


def test_job_fora_do_estado_e_primeira_publicacao_mesmo_com_o_output_gravado() -> None:
    # O apply que cai antes de criar o Job deixa o output; o estado não tem o Job.
    assert _rodar_imagem_do_job("module.mam.google_cloud_run_v2_job.ocr") == (0, "[]")


def test_job_no_estado_le_a_imagem_pelo_nome_do_output() -> None:
    estado = "module.mam.google_cloud_run_v2_job.ocr_gpu"
    assert _rodar_imagem_do_job(estado) == (0, "[imagem-de-mam-ocr-gpu]")


def test_job_no_estado_que_o_describe_nao_acha_para_a_publicacao() -> None:
    estado = "module.mam.google_cloud_run_v2_job.ocr_gpu"
    codigo, _ = _rodar_imagem_do_job(estado, describe_falha=True)
    assert codigo != 0


_INDICE_COM_ATESTACAO = json.dumps(
    {
        "manifests": [
            {
                "digest": "sha256:amd64",
                "platform": {"os": "linux", "architecture": "amd64"},
            },
            {
                "digest": "sha256:atestacao",
                "platform": {"os": "unknown", "architecture": "unknown"},
            },
        ]
    }
)


def _rodar_digest(manifesto: str, curl_falha: bool = False) -> tuple[int, str]:
    """Roda o digest do deploy-dev.sh com curl e gc simulados; o registro devolve `manifesto`."""
    curl = "return 22" if curl_falha else f"echo {shlex.quote(manifesto)}"
    script = f"""set -euo pipefail
curl() {{ {curl}; }}
gc() {{ [[ $1 == auth ]] && echo token || echo sha256:indice; }}
{_funcao_do_deploy("amd64_do_indice")}
{_funcao_do_deploy("digest")}
IMAGEM=$(digest us-east4-docker.pkg.dev/p/r/ocr-gpu:abc123)
echo "$IMAGEM"
"""
    feito = subprocess.run(
        ["bash", "-c", script], check=False, capture_output=True, text=True
    )
    return feito.returncode, feito.stdout.strip()


def test_o_digest_publicado_e_o_da_imagem_amd64_e_nao_o_do_indice_com_a_atestacao() -> (
    None
):
    assert _rodar_digest(_INDICE_COM_ATESTACAO) == (
        0,
        "us-east4-docker.pkg.dev/p/r/ocr-gpu@sha256:amd64",
    )


def test_imagem_sem_indice_fica_com_o_digest_do_registro() -> None:
    manifesto = json.dumps({"schemaVersion": 2, "layers": []})
    assert _rodar_digest(manifesto) == (
        0,
        "us-east4-docker.pkg.dev/p/r/ocr-gpu@sha256:indice",
    )


@pytest.mark.parametrize(
    "manifesto",
    [
        "",
        json.dumps({"manifests": [json.loads(_INDICE_COM_ATESTACAO)["manifests"][1]]}),
    ],
    ids=["vazio", "indice-sem-amd64"],
)
def test_manifesto_sem_amd64_para_a_publicacao(manifesto: str) -> None:
    # Cair no digest do índice traria de volta o teste de GPU a cada deploy (#346).
    codigo, _ = _rodar_digest(manifesto)
    assert codigo != 0


def test_registro_que_nao_responde_para_a_publicacao() -> None:
    codigo, _ = _rodar_digest(_INDICE_COM_ATESTACAO, curl_falha=True)
    assert codigo != 0


def test_o_comentario_do_deploy_diz_que_mesma_imagem_nao_gera_revisao() -> None:
    deploy = (RAIZ / "scripts" / "deploy-dev.sh").read_text()
    assert "também gere revisão nova" not in deploy
    assert "nenhuma revisão nova" in deploy
