"""Pré-voo do apply (api/pre_voo.py) com uma API falsa: o que vai a cada API e o que falha."""

import json
from pathlib import Path
from typing import Any

from api import pre_voo

RAIZ = Path(__file__).parents[2]


class ApiFalsa:
    """Anota as chamadas; responde com o que `respostas` disser para o começo da URL."""

    def __init__(self, respostas: dict[str, Any] | None = None) -> None:
        self.chamadas: list[tuple[str, str, Any]] = []
        self.respostas = respostas or {}

    def __call__(self, metodo: str, url: str, corpo: Any) -> dict[str, Any]:
        self.chamadas.append((metodo, url, corpo))
        for inicio, resposta in self.respostas.items():
            if f"{metodo} {url}".startswith(inicio):
                if isinstance(resposta, Exception):
                    raise resposta
                return dict(resposta)
        return {"done": True}


def _plano(*mudancas: dict[str, Any]) -> dict[str, Any]:
    return {
        "variables": {"projeto": {"value": "p"}},
        "resource_changes": list(mudancas),
    }


def _mudanca(
    tipo: str, acoes: list[str], depois: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    change = {
        "actions": acoes,
        "after": depois,
        "after_unknown": extra.get("desconhecido", {}),
    }
    return {"address": f"{tipo}.x", "type": tipo, "change": change}


JOB = {
    "name": "mam-ocr-gpu",
    "project": "p",
    "location": "us-east4",
    "deletion_protection": False,
    "launch_stage": "BETA",
    "labels": {"app": "mam"},
    "template": [
        {
            "task_count": 1,
            "template": [
                {
                    "max_retries": 0,
                    "timeout": "21600s",
                    "gpu_zonal_redundancy_disabled": True,
                    "node_selector": [{"accelerator": "nvidia-l4"}],
                    "vpc_access": [
                        {
                            "egress": "ALL_TRAFFIC",
                            "network_interfaces": [
                                {"network": "n", "subnetwork": None}
                            ],
                        }
                    ],
                    "containers": [
                        {
                            "image": "img@sha256:1",
                            "env": [
                                {"name": "A", "value": "1"},
                                {"name": "B", "value": "2"},
                            ],
                            "resources": [
                                {"limits": {"cpu": "4", "nvidia.com/gpu": "1"}}
                            ],
                            "volume_mounts": [
                                {"name": "saida", "mount_path": "/saida"}
                            ],
                            "command": [],
                        }
                    ],
                }
            ],
        }
    ],
}


def test_o_corpo_do_job_segue_a_api_v2_sem_o_que_o_provider_nao_manda() -> None:
    desconhecido = {
        "template": [
            {
                "template": [
                    {"vpc_access": [{"network_interfaces": [{"subnetwork": True}]}]}
                ]
            }
        ]
    }
    corpo = pre_voo.corpo_do_run("google_cloud_run_v2_job", JOB, desconhecido)

    assert corpo["launchStage"] == "BETA"
    assert (
        "name" not in corpo
        and "labels" not in corpo
        and "deletionProtection" not in corpo
    )
    tarefa = corpo["template"]["template"]
    assert (
        tarefa["timeout"] == "21600s" and tarefa["gpuZonalRedundancyDisabled"] is True
    )
    assert "maxRetries" not in tarefa  # zero não vai, como no provider
    assert tarefa["nodeSelector"] == {"accelerator": "nvidia-l4"}
    assert tarefa["vpcAccess"]["networkInterfaces"] == [{"network": "n"}]
    conteiner = tarefa["containers"][0]
    assert conteiner["env"] == [
        {"name": "A", "value": "1"},
        {"name": "B", "value": "2"},
    ]
    assert conteiner["resources"] == {"limits": {"cpu": "4", "nvidia.com/gpu": "1"}}
    assert conteiner["volumeMounts"] == [{"name": "saida", "mountPath": "/saida"}]
    assert "command" not in conteiner


def test_false_nao_vai_no_corpo_porque_a_api_le_a_presenca_do_campo() -> None:
    cpu = json.loads(json.dumps(JOB))
    cpu["template"][0]["template"][0]["gpu_zonal_redundancy_disabled"] = False
    corpo = pre_voo.corpo_do_run("google_cloud_run_v2_job", cpu, {})

    assert "gpuZonalRedundancyDisabled" not in corpo["template"]["template"]


def test_job_novo_vai_ao_validate_only_da_criacao_e_o_que_muda_ao_da_atualizacao() -> (
    None
):
    api = ApiFalsa()
    plano = _plano(
        _mudanca("google_cloud_run_v2_job", ["create"], JOB),
        _mudanca("google_cloud_run_v2_job", ["update"], JOB),
    )

    assert pre_voo.conferir(plano, api) == []
    (metodo1, url1, _), (metodo2, url2, _) = api.chamadas
    base = "https://run.googleapis.com/v2/projects/p/locations/us-east4/jobs"
    assert (metodo1, url1) == ("POST", f"{base}?jobId=mam-ocr-gpu&validateOnly=true")
    assert (metodo2, url2) == ("PATCH", f"{base}/mam-ocr-gpu?validateOnly=true")


def test_a_recusa_da_api_vira_falha_e_os_outros_recursos_continuam() -> None:
    erro = pre_voo.ErroDaApi("400 Long running GPU jobs ... at least as BETA")
    api = ApiFalsa({"POST https://run.googleapis.com": erro})
    painel = {"dashboard_json": json.dumps({"displayName": "d", "etag": "e"})}
    plano = _plano(
        _mudanca("google_cloud_run_v2_job", ["create"], JOB),
        _mudanca("google_monitoring_dashboard", ["update"], painel),
    )

    falhas = pre_voo.conferir(plano, api)

    assert len(falhas) == 1 and "BETA" in falhas[0]
    metodo, url, corpo = api.chamadas[-1]
    assert (metodo, url) == (
        "POST",
        "https://monitoring.googleapis.com/v1/projects/p/dashboards?validateOnly=true",
    )
    assert corpo == {"displayName": "d"}


def _alerta(filtro: str, alinhador: str, redutor: str | None = None) -> dict[str, Any]:
    agregacao = {
        "alignment_period": "86400s",
        "per_series_aligner": alinhador,
        "cross_series_reducer": redutor,
        "group_by_fields": ["metric.label.etapa"] if redutor else None,
    }
    limiar = {"filter": filtro, "aggregations": [agregacao]}
    return {"conditions": [{"condition_threshold": [limiar]}]}


def test_alerta_sem_resource_type_falha_sem_chamar_a_api() -> None:
    api = ApiFalsa()
    alerta = _alerta('metric.type="logging.googleapis.com/user/m"', "ALIGN_DELTA")
    plano = _plano(_mudanca("google_monitoring_alert_policy", ["create"], alerta))

    falhas = pre_voo.conferir(plano, api)

    assert len(falhas) == 1 and "resource.type" in falhas[0]
    assert api.chamadas == []


def test_metrica_que_ja_existe_tem_a_agregacao_conferida_no_time_series() -> None:
    api = ApiFalsa()
    filtro = (
        'metric.type="logging.googleapis.com/user/m" AND resource.type="cloud_run_job"'
    )
    alerta = _alerta(filtro, "ALIGN_DELTA", "REDUCE_SUM")
    plano = _plano(_mudanca("google_monitoring_alert_policy", ["create"], alerta))

    assert pre_voo.conferir(plano, api) == []
    metodo, url, _ = api.chamadas[-1]
    assert metodo == "GET" and "/v3/projects/p/timeSeries?" in url
    assert "aggregation.perSeriesAligner=ALIGN_DELTA" in url
    assert "aggregation.crossSeriesReducer=REDUCE_SUM" in url
    assert "aggregation.groupByFields=metric.label.etapa" in url
    assert "view=" not in url  # com view=HEADERS a API não confere o alinhador


def test_metrica_criada_no_mesmo_apply_tem_o_alinhador_conferido_pela_tabela() -> None:
    nao_existe = pre_voo.ErroDaApi("404 Could not find descriptor")
    api = ApiFalsa(
        {
            "GET https://monitoring.googleapis.com/v3/projects/p/metricDescriptors": nao_existe
        }
    )
    metrica = {
        "name": "mam_pct",
        "metric_descriptor": [{"metric_kind": "DELTA", "value_type": "DISTRIBUTION"}],
    }
    filtro = 'metric.type="logging.googleapis.com/user/mam_pct" AND resource.type="cloud_run_job"'
    plano = _plano(
        _mudanca("google_logging_metric", ["create"], metrica),
        _mudanca(
            "google_monitoring_alert_policy", ["create"], _alerta(filtro, "ALIGN_MEAN")
        ),
    )

    falhas = pre_voo.conferir(plano, api)

    assert (
        len(falhas) == 1
        and "ALIGN_MEAN não se aplica a DELTA DISTRIBUTION" in falhas[0]
    )
    plano["resource_changes"][1] = _mudanca(
        "google_monitoring_alert_policy",
        ["create"],
        _alerta(filtro, "ALIGN_DELTA", "REDUCE_MEAN"),
    )
    assert pre_voo.conferir(plano, api) == []


WORKFLOW = {
    "project": "p",
    "region": "southamerica-east1",
    "source_contents": "main:\n  steps: []\n",
    "service_account": "projects/p/serviceAccounts/o@p.iam.gserviceaccount.com",
}
BASE_DO_WORKFLOW = "https://workflows.googleapis.com/v1/projects/p/locations/southamerica-east1/workflows"


def test_workflow_e_publicado_com_nome_descartavel_e_apagado_mesmo_se_nao_compilar() -> (
    None
):
    # A recusa vem na operação, com o workflow já criado (o run 41662346067).
    recusa = {
        "name": "projects/p/locations/southamerica-east1/operations/o",
        "done": True,
        "error": {
            "message": "symbol 'mensagem' is neither a variable nor a sub-workflow name"
        },
    }
    api = ApiFalsa({"POST https://workflows.googleapis.com": recusa})
    plano = _plano(_mudanca("google_workflows_workflow", ["update"], WORKFLOW))

    falhas = pre_voo.conferir(plano, api, dormir=lambda _: None)

    assert len(falhas) == 1 and "mensagem" in falhas[0]
    (criar, url_criar, corpo), (apagar, url_apagar, _) = api.chamadas
    assert criar == "POST" and url_criar.startswith(
        f"{BASE_DO_WORKFLOW}?workflowId=pre-voo-"
    )
    assert corpo["sourceContents"] == WORKFLOW["source_contents"]
    assert corpo["serviceAccount"] == WORKFLOW["service_account"]
    nome = url_criar.split("workflowId=")[1]
    assert (apagar, url_apagar) == ("DELETE", f"{BASE_DO_WORKFLOW}/{nome}")


def test_workflow_recusado_antes_de_existir_falha_e_nao_tenta_apagar() -> None:
    api = ApiFalsa(
        {
            "POST https://workflows.googleapis.com": pre_voo.ErroDaApi(
                "403 sem permissão"
            )
        }
    )
    plano = _plano(_mudanca("google_workflows_workflow", ["update"], WORKFLOW))

    falhas = pre_voo.conferir(plano, api, dormir=lambda _: None)

    assert len(falhas) == 1 and "403" in falhas[0]
    assert [metodo for metodo, _, _ in api.chamadas] == ["POST"]


def test_o_que_o_pre_voo_nao_confere_e_o_que_so_sai_do_plano_ficam_de_fora() -> None:
    api = ApiFalsa()
    plano = _plano(
        _mudanca("google_storage_bucket", ["create"], {"name": "b"}),
        _mudanca("google_cloud_run_v2_job", ["delete"], JOB),
        _mudanca("google_cloud_run_v2_job", ["no-op"], JOB),
    )

    assert pre_voo.conferir(plano, api) == []
    assert api.chamadas == []


def test_a_trava_roda_o_pre_voo_depois_da_destruicao_e_antes_do_apply() -> None:
    trava = (RAIZ / "scripts" / "aplicar-sem-destruir.sh").read_text()

    destruicao = trava.index("PERMITIR_DESTRUICAO")
    pre_voo_ = trava.index('python3 -m api.pre_voo "$PLANO_JSON"')
    apply = trava.index('terraform -chdir=infra apply -input=false "$PLANO"')
    assert destruicao < pre_voo_ < apply
