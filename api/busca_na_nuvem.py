"""Adaptadores reais da busca: descrição da foto pelo Gemini e Ranking API."""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

import google.auth
import google.auth.transport.requests
import requests

from api.busca import Ranking
from api.gemini import ErroHttp, SessaoHttp, Transporte, TransporteVertex
from api.indice_da_busca import Registro

log = logging.getLogger(__name__)

TEMPO_DA_RANKING_S = 5.0
# O limite de registros por pedido da Ranking API (RankRequest.records: no máximo 200);
# a busca funde várias cláusulas de até 100 registros, então passar disso é comum.
REGISTROS_POR_PEDIDO = 200
MODELO_DA_RANKING = "semantic-ranker-default@latest"


def _postar(
    sessao: SessaoHttp, url: str, corpo: dict[str, Any], timeout_s: float
) -> dict[str, Any]:
    """O JSON da resposta; timeout, queda e corpo ilegível também viram `ErroHttp`."""
    try:
        resposta = sessao.post(url, json=corpo, timeout=timeout_s)
    except (requests.RequestException, OSError) as e:
        raise ErroHttp(503) from e
    if resposta.status_code != 200:
        raise ErroHttp(resposta.status_code)
    try:
        return cast(dict[str, Any], resposta.json())
    except ValueError as e:
        raise ErroHttp(502) from e


def _texto_do_registro(r: Registro) -> str:
    return r.texto or r.descricao or ""


class RankingReal:
    """A Ranking API (Discovery Engine): devolve os registros na ordem da API."""

    def __init__(
        self,
        projeto: str,
        configuracao: str,
        sessao: SessaoHttp,
        modelo: str = MODELO_DA_RANKING,
    ) -> None:
        self._url = (
            f"https://discoveryengine.googleapis.com/v1/projects/{projeto}"
            f"/locations/global/rankingConfigs/{configuracao}:rank"
        )
        self._modelo = modelo
        self._sessao = sessao

    def reordenar(self, consulta: str, registros: list[Registro]) -> list[Registro]:
        # Sem texto não há o que ranquear: esses registros e os que passam do limite do
        # pedido ficam no fim, na ordem em que vieram.
        enviados = [r for r in registros if _texto_do_registro(r)][
            :REGISTROS_POR_PEDIDO
        ]
        if not enviados:
            return registros
        dados = _postar(
            self._sessao,
            self._url,
            {
                "model": self._modelo,
                "query": consulta,
                "records": [
                    {"id": r.id, "content": _texto_do_registro(r)} for r in enviados
                ],
                "ignoreRecordDetailsInResponse": True,
            },
            TEMPO_DA_RANKING_S,
        )
        por_id = {r.id: r for r in enviados}
        ordem: list[Registro] = []
        for item in dados.get("records") or []:
            registro = por_id.pop(item.get("id"), None)
            if registro is not None:
                ordem.append(registro)
        vistos = {r.id for r in ordem}
        return ordem + [r for r in registros if r.id not in vistos]


@dataclass(frozen=True)
class AdaptadoresDaBusca:
    transporte_da_consulta: Transporte | None = None
    ranking: Ranking | None = None


def adaptadores_da_busca(
    ambiente: Mapping[str, str], sessao: Callable[[], SessaoHttp] | None = None
) -> AdaptadoresDaBusca:
    """Liga o modelo só para descrever fotos; a Ranking depende da configuração."""
    projeto = ambiente.get("GCP_PROJECT_ID")
    if not projeto:
        return AdaptadoresDaBusca()
    sessao_unica: SessaoHttp | None = None

    def sessao_http() -> SessaoHttp:
        nonlocal sessao_unica
        if sessao_unica is None:
            sessao_unica = (sessao or _sessao_autorizada)()
        return sessao_unica

    configuracao = ambiente.get("RANKING_CONFIG")
    return AdaptadoresDaBusca(
        transporte_da_consulta=TransporteVertex(projeto, sessao_http(), etapa="busca"),
        ranking=(
            RankingReal(projeto, configuracao, sessao_http()) if configuracao else None
        ),
    )


def _sessao_autorizada() -> SessaoHttp:
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return cast(
        SessaoHttp,
        google.auth.transport.requests.AuthorizedSession(credenciais),  # type: ignore[no-untyped-call]
    )
