"""Pré-voo do apply: confere na própria nuvem, antes de aplicar, o que o plan não confere.

O `terraform plan` confere a sintaxe e os tipos, mas não as regras de cada API (o GPU de
mais de uma hora só em BETA, o alinhador que não serve para a métrica, o filtro do alerta
sem `resource.type`, o workflow que não compila: os deploys de 2026-11-03). O
`scripts/aplicar-sem-destruir.sh` roda este módulo sobre o plan gravado, como a conta do
apply, e só aplica se tudo passar. Para cada recurso que o plan cria ou muda:

- Job e serviço do Cloud Run: o corpo REST, montado do plan, vai ao `validateOnly` da API.
- Painel do Monitoring: o `dashboard_json` vai ao `validateOnly` da API.
- Alerta do Monitoring, só nas condições de limiar (`condition_threshold`): o filtro precisa
  de `resource.type`, e a agregação vai ao `timeSeries.list`, que recusa o alinhador errado
  como o alerta recusaria. A métrica de log que o plan cria ou muda vale pela tabela da API.
- Recriação (delete+create) fica de fora: o recurso ainda existe.
- Workflow: a definição é publicada com um nome descartável e apagada em seguida (a API do
  Workflows não tem `validateOnly`, e a compilação só acontece na publicação).

Só a biblioteca padrão: roda no CD sem instalar nada (`python3 -m api.pre_voo <plano.json>`).
O token vem de `PRE_VOO_TOKEN` ou do `gcloud`, pela conta de `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any

Chamar = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]


class ErroDaApi(Exception):
    pass


RUN = "https://run.googleapis.com/v2"
MONITORING = "https://monitoring.googleapis.com"
WORKFLOWS = "https://workflows.googleapis.com/v1"

# Campos de topo que a API do Cloud Run aceita no corpo (o resto do plan é do provider ou
# só de saída) e os blocos que são listas na API (no plan, todo bloco é lista).
_TOPO_DO_RUN = {
    "google_cloud_run_v2_job": {
        "launch_stage",
        "template",
        "binary_authorization",
        "client",
        "client_version",
    },
    "google_cloud_run_v2_service": {
        "launch_stage",
        "template",
        "traffic",
        "ingress",
        "scaling",
        "invoker_iam_disabled",
        "default_uri_disabled",
        "custom_audiences",
        "binary_authorization",
        "client",
        "client_version",
        "description",
    },
}
_LISTAS_DO_RUN = {
    "containers",
    "env",
    "volumes",
    "volume_mounts",
    "network_interfaces",
    "ports",
    "args",
    "command",
    "tags",
    "items",
    "depends_on",
    "mount_options",
    "traffic",
    "custom_audiences",
    "http_headers",
}

# Alinhadores pela documentação da API (Aggregation.Aligner): os tipos de métrica e de
# valor que cada um aceita. Só para a métrica que o plan cria ou muda; a que ele não toca
# vai ao timeSeries.list.
_ALINHADORES: dict[str, tuple[set[str], set[str]]] = {
    "ALIGN_NONE": (
        {"GAUGE", "DELTA", "CUMULATIVE"},
        {"INT64", "DOUBLE", "DISTRIBUTION", "BOOL", "STRING"},
    ),
    "ALIGN_DELTA": ({"DELTA", "CUMULATIVE"}, {"INT64", "DOUBLE", "DISTRIBUTION"}),
    "ALIGN_RATE": ({"DELTA", "CUMULATIVE"}, {"INT64", "DOUBLE"}),
    "ALIGN_MEAN": ({"GAUGE", "DELTA"}, {"INT64", "DOUBLE"}),
    "ALIGN_SUM": ({"GAUGE", "DELTA"}, {"INT64", "DOUBLE", "DISTRIBUTION"}),
    "ALIGN_MIN": ({"GAUGE", "DELTA"}, {"INT64", "DOUBLE"}),
    "ALIGN_MAX": ({"GAUGE", "DELTA"}, {"INT64", "DOUBLE"}),
    "ALIGN_COUNT": ({"GAUGE", "DELTA"}, {"INT64", "DOUBLE", "BOOL"}),
    "ALIGN_PERCENTILE_99": ({"GAUGE", "DELTA"}, {"DISTRIBUTION"}),
    "ALIGN_PERCENTILE_95": ({"GAUGE", "DELTA"}, {"DISTRIBUTION"}),
    "ALIGN_PERCENTILE_50": ({"GAUGE", "DELTA"}, {"DISTRIBUTION"}),
    "ALIGN_PERCENTILE_05": ({"GAUGE", "DELTA"}, {"DISTRIBUTION"}),
}


def _camel(nome: str) -> str:
    return re.sub(r"_([a-z0-9])", lambda m: m.group(1).upper(), nome)


def _sem_desconhecidos(valor: Any, desconhecido: Any) -> Any:
    """Tira o que o plan ainda não sabe (calculado no apply) e não pode ir no corpo."""
    if desconhecido is True:
        return None
    if isinstance(valor, dict):
        d = desconhecido if isinstance(desconhecido, dict) else {}
        return {k: _sem_desconhecidos(v, d.get(k)) for k, v in valor.items()}
    if isinstance(valor, list):
        lista = desconhecido if isinstance(desconhecido, list) else []
        return [
            _sem_desconhecidos(v, lista[i] if i < len(lista) else None)
            for i, v in enumerate(valor)
        ]
    return valor


def _vazio(valor: Any) -> bool:
    """O que o provider não manda: vazio, `false` e o número zero (a API lê a presença de
    um campo opcional, como `gpuZonalRedundancyDisabled: false`, como configurado)."""
    zero = type(valor) in (int, float) and valor == 0
    return valor is None or valor is False or zero or valor in ("", [], {})


def _bloco(valores: dict[str, Any]) -> dict[str, Any]:
    corpo: dict[str, Any] = {}
    for chave, valor in valores.items():
        if _vazio(valor):
            continue
        if isinstance(valor, dict):  # mapa (limits, labels): chaves como estão
            corpo[_camel(chave)] = {k: v for k, v in valor.items() if v is not None}
        elif isinstance(valor, list) and isinstance(valor[0], dict):
            itens = [b for b in (_bloco(v) for v in valor if v is not None) if b]
            if itens:
                corpo[_camel(chave)] = itens if chave in _LISTAS_DO_RUN else itens[0]
        else:
            corpo[_camel(chave)] = valor
    return corpo


def corpo_do_run(
    tipo: str, depois: dict[str, Any], desconhecido: Any
) -> dict[str, Any]:
    """O corpo REST v2 do Job ou do serviço, a partir dos valores do plan."""
    valores = _sem_desconhecidos(depois, desconhecido)
    return _bloco({k: v for k, v in valores.items() if k in _TOPO_DO_RUN[tipo]})


def _conferir_run(mudanca: dict[str, Any], chamar: Chamar) -> None:
    tipo, depois = mudanca["type"], mudanca["change"]["after"]
    corpo = corpo_do_run(tipo, depois, mudanca["change"].get("after_unknown"))
    colecao = "jobs" if tipo == "google_cloud_run_v2_job" else "services"
    pai = f"projects/{depois['project']}/locations/{depois['location']}"
    if "create" in mudanca["change"]["actions"]:
        campo = "jobId" if colecao == "jobs" else "serviceId"
        url = f"{RUN}/{pai}/{colecao}?{campo}={depois['name']}&validateOnly=true"
        chamar("POST", url, corpo)
    else:
        chamar(
            "PATCH", f"{RUN}/{pai}/{colecao}/{depois['name']}?validateOnly=true", corpo
        )


def _conhecido(depois: dict[str, Any], campo: str) -> Any:
    if depois.get(campo) is None:
        raise ErroDaApi(
            f"{campo} só se conhece no apply: o pré-voo não consegue conferir"
        )
    return depois[campo]


def _conferir_painel(mudanca: dict[str, Any], chamar: Chamar, projeto: str) -> None:
    painel = json.loads(_conhecido(mudanca["change"]["after"], "dashboard_json"))
    painel.pop("name", None)
    painel.pop("etag", None)
    chamar(
        "POST",
        f"{MONITORING}/v1/projects/{projeto}/dashboards?validateOnly=true",
        painel,
    )


def _metricas_do_plano(plano: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Tipo e valor de cada métrica de log que o plan cria ou muda."""
    metricas = {}
    for mudanca in plano.get("resource_changes", []):
        depois = mudanca["change"].get("after") or {}
        muda = {"create", "update"} & set(mudanca["change"]["actions"])
        if (
            mudanca.get("type") == "google_logging_metric"
            and muda
            and depois.get("name")
        ):
            descritor = (depois.get("metric_descriptor") or [{}])[0]
            tipo = f"logging.googleapis.com/user/{depois['name']}"
            metricas[tipo] = (
                descritor.get("metric_kind", "DELTA"),
                descritor.get("value_type", "INT64"),
            )
    return metricas


def _conferir_alerta(
    mudanca: dict[str, Any],
    chamar: Chamar,
    projeto: str,
    metricas_novas: dict[str, tuple[str, str]],
) -> None:
    for condicao in mudanca["change"]["after"].get("conditions") or []:
        for limiar in condicao.get("condition_threshold") or []:
            filtro = limiar["filter"]
            if "resource.type" not in filtro:
                raise ErroDaApi(f"o filtro precisa de resource.type: {filtro}")
            tipo = re.search(r'metric\.type\s*=\s*"([^"]+)"', filtro)
            for agregacao in limiar.get("aggregations") or []:
                alinhador = agregacao.get("per_series_aligner") or "ALIGN_NONE"
                # A métrica que o plan cria ou muda vale pelo plan (o descritor de hoje
                # pode ser o antigo); a que ele não toca vai ao timeSeries.
                if tipo and tipo.group(1) in metricas_novas:
                    tipo_da_metrica, valor = metricas_novas[tipo.group(1)]
                    aceitos = _ALINHADORES.get(alinhador)
                    if aceitos is None:
                        raise ErroDaApi(
                            f"alinhador {alinhador} fora da tabela do pré-voo"
                        )
                    if tipo_da_metrica not in aceitos[0] or valor not in aceitos[1]:
                        raise ErroDaApi(
                            f"{alinhador} não se aplica a {tipo_da_metrica} {valor} ({tipo.group(1)})"
                        )
                    continue
                agora = time.time()
                parametros = {
                    "filter": filtro,
                    "interval.startTime": _rfc3339(agora - 7200),
                    "interval.endTime": _rfc3339(agora),
                    "aggregation.alignmentPeriod": agregacao.get("alignment_period")
                    or "60s",
                    "aggregation.perSeriesAligner": alinhador,
                }
                if agregacao.get("cross_series_reducer"):
                    parametros["aggregation.crossSeriesReducer"] = agregacao[
                        "cross_series_reducer"
                    ]
                consulta = urllib.parse.urlencode(parametros) + "".join(
                    "&aggregation.groupByFields=" + urllib.parse.quote(c)
                    for c in agregacao.get("group_by_fields") or []
                )
                chamar(
                    "GET",
                    f"{MONITORING}/v3/projects/{projeto}/timeSeries?{consulta}",
                    None,
                )


def _rfc3339(segundos: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(segundos))


def _conferir_workflow(
    mudanca: dict[str, Any], chamar: Chamar, dormir: Callable[[float], None]
) -> None:
    depois = mudanca["change"]["after"]
    pai = f"projects/{depois['project']}/locations/{depois['region']}"
    nome = f"pre-voo-{uuid.uuid4().hex[:12]}"
    corpo: dict[str, Any] = {"sourceContents": _conhecido(depois, "source_contents")}
    if depois.get("service_account"):
        corpo["serviceAccount"] = depois["service_account"]
    operacao = chamar("POST", f"{WORKFLOWS}/{pai}/workflows?workflowId={nome}", corpo)
    try:
        _esperar(operacao, chamar, dormir)
    finally:
        try:
            _esperar(
                chamar("DELETE", f"{WORKFLOWS}/{pai}/workflows/{nome}", None),
                chamar,
                dormir,
            )
        except (
            ErroDaApi,
            OSError,
        ) as erro:  # rede ou recusa: o que sobra não derruba o deploy
            if "404" not in str(erro):  # não chegou a existir: nada a apagar
                aviso = f"  aviso: apague à mão o workflow {pai}/{nome}: {erro}"
                print(aviso, file=sys.stderr)


def _esperar(
    operacao: dict[str, Any], chamar: Chamar, dormir: Callable[[float], None]
) -> None:
    for _ in range(120):
        if operacao.get("done"):
            break
        dormir(5)
        operacao = chamar("GET", f"{WORKFLOWS}/{operacao['name']}", None)
    else:
        raise ErroDaApi(f"a operação {operacao.get('name')} não terminou em 10 min")
    if "error" in operacao:
        raise ErroDaApi(operacao["error"].get("message", str(operacao["error"])))


def conferir(
    plano: dict[str, Any], chamar: Chamar, dormir: Callable[[float], None] = time.sleep
) -> list[str]:
    """Confere cada recurso que o plan cria ou muda; devolve as falhas."""
    mudancas = a_conferir(plano)
    if not mudancas:
        return []
    projeto = _projeto(plano)
    metricas_novas = _metricas_do_plano(plano)
    falhas = []
    for mudanca in mudancas:
        tipo = mudanca["type"]
        try:
            if tipo in _TOPO_DO_RUN:
                _conferir_run(mudanca, chamar)
            elif tipo == "google_monitoring_dashboard":
                _conferir_painel(mudanca, chamar, projeto)
            elif tipo == "google_monitoring_alert_policy":
                _conferir_alerta(mudanca, chamar, projeto, metricas_novas)
            elif tipo == "google_workflows_workflow":
                _conferir_workflow(mudanca, chamar, dormir)
            else:
                continue
        except ErroDaApi as erro:
            falhas.append(f"{mudanca['address']}: {erro}")
            print(f"  FALHA {mudanca['address']}: {erro}")
            continue
        print(f"  ok    {mudanca['address']}")
    return falhas


_CONFERIDOS = set(_TOPO_DO_RUN) | {
    "google_monitoring_dashboard",
    "google_monitoring_alert_policy",
    "google_workflows_workflow",
}


def a_conferir(plano: dict[str, Any]) -> list[dict[str, Any]]:
    """Os recursos que o plan cria ou muda e que o pré-voo sabe conferir."""
    return [
        m
        for m in plano.get("resource_changes", [])
        if m.get("type") in _CONFERIDOS
        and {"create", "update"} & set(m["change"]["actions"])
        # Recriação (delete+create, só com PERMITIR_DESTRUICAO=sim): o recurso ainda
        # existe e a criação em validateOnly daria 409. Fica fora do pré-voo.
        and "delete" not in m["change"]["actions"]
    ]


def _projeto(plano: dict[str, Any]) -> str:
    variaveis = plano.get("variables", {})
    return str(
        variaveis.get("projeto", {}).get("value") or os.environ["GCP_PROJECT_ID"]
    )


def chamar_com_token(token: str) -> Chamar:
    def chamar(metodo: str, url: str, corpo: dict[str, Any] | None) -> dict[str, Any]:
        dados = json.dumps(corpo).encode() if corpo is not None else None
        pedido = urllib.request.Request(url, data=dados, method=metodo)
        pedido.add_header("Authorization", f"Bearer {token}")
        pedido.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(pedido, timeout=120) as resposta:
                texto = resposta.read().decode()
        except urllib.error.HTTPError as erro:
            detalhe = erro.read().decode()
            try:
                mensagem = json.loads(detalhe)["error"]["message"]
            except (ValueError, KeyError, TypeError):
                mensagem = detalhe[:300]
            raise ErroDaApi(f"{erro.code} {mensagem}") from None
        return json.loads(texto) if texto else {}

    return chamar


def _token() -> str:
    if os.environ.get("PRE_VOO_TOKEN"):
        return os.environ["PRE_VOO_TOKEN"]
    comando = ["gcloud", "auth", "print-access-token"]
    if os.environ.get("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT"):
        comando.append(
            f"--impersonate-service-account={os.environ['GOOGLE_IMPERSONATE_SERVICE_ACCOUNT']}"
        )
    return subprocess.run(
        comando, check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> None:
    with open(sys.argv[1]) as arquivo:
        plano = json.load(arquivo)
    if not a_conferir(plano):
        print("Pré-voo: nada que ele confira muda neste plan.")
        return
    print("Pré-voo: o que o plan cria ou muda, conferido na nuvem antes do apply.")
    falhas = conferir(plano, chamar_com_token(_token()))
    if falhas:
        print(
            f"Pré-voo: {len(falhas)} recurso(s) a API recusaria; nada foi aplicado.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print("Pré-voo: tudo passou.")


if __name__ == "__main__":
    main()
