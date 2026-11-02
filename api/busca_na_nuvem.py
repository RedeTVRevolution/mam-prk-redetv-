"""Adaptadores reais da busca: Model Armor e Ranking API, e a montagem pelo ambiente.

O Model Armor julga a consulta antes de o modelo vê-la; a Ranking API reordena os
registros pela consulta de texto livre. As duas só lançam erro: o `entender` e a busca
já caem no plano B e na ordem do índice (`api/entendimento_da_consulta.py`, `api/busca.py`).
Os nomes (modelo do Model Armor, região, configuração da Ranking) vêm do ambiente, que
o `infra/modulos/mam/main.tf` preenche.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

import google.auth
import google.auth.transport.requests
import requests

from api.busca import Ranking
from api.entendimento_da_consulta import ModelArmor
from api.gemini import ErroHttp, SessaoHttp, Transporte, TransporteVertex
from api.indice_da_busca import Registro

log = logging.getLogger(__name__)

TEMPO_DO_MODEL_ARMOR_S = 3.0
TEMPO_DA_RANKING_S = 5.0
# O limite de registros por pedido da Ranking API (RankRequest.records: no máximo 200);
# a busca funde várias cláusulas de até 100 registros, então passar disso é comum.
REGISTROS_POR_PEDIDO = 200
MODELO_DA_RANKING = "semantic-ranker-default@latest"


class VeredictoIndefinido(Exception):
    """O Model Armor respondeu 200, mas sem dizer se há injeção."""


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


class ModelArmorReal:
    """`sanitizeUserPrompt` num modelo (template) com o filtro de injeção e jailbreak."""

    def __init__(
        self, projeto: str, regiao: str, modelo: str, sessao: SessaoHttp
    ) -> None:
        self._url = (
            f"https://modelarmor.{regiao}.rep.googleapis.com/v1/projects/{projeto}"
            f"/locations/{regiao}/templates/{modelo}:sanitizeUserPrompt"
        )
        self._sessao = sessao

    def acusa_injecao(self, texto: str) -> bool:
        dados = _postar(
            self._sessao,
            self._url,
            {"userPromptData": {"text": texto}},
            TEMPO_DO_MODEL_ARMOR_S,
        )
        resultado = (dados.get("sanitizationResult") or {}).get("filterResults") or {}
        filtro = (resultado.get("pi_and_jailbreak") or {}).get(
            "piAndJailbreakFilterResult"
        ) or {}
        estado = filtro.get("matchState")
        if estado == "MATCH_FOUND":
            return True
        if estado == "NO_MATCH_FOUND":
            return False
        raise VeredictoIndefinido(f"matchState={estado!r}")


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
    armor: ModelArmor | None = None
    ranking: Ranking | None = None


def adaptadores_da_busca(
    ambiente: Mapping[str, str], sessao: Callable[[], SessaoHttp] | None = None
) -> AdaptadoresDaBusca:
    """Liga o que o ambiente configura; o resto fica `None`, e a busca usa os substitutos.

    O Model Armor e o modelo da consulta entram juntos: sem o veredito, o modelo nunca é
    chamado. A consulta usa o transporte da decupagem, mas com `Chamada.texto` ele vai em
    Standard, sem os cabeçalhos do Flex (a consulta é interativa).
    """
    projeto = ambiente.get("GCP_PROJECT_ID")
    if not projeto:
        return AdaptadoresDaBusca()
    sessao_unica: SessaoHttp | None = None

    def sessao_http() -> SessaoHttp:
        nonlocal sessao_unica
        if sessao_unica is None:
            sessao_unica = (sessao or _sessao_autorizada)()
        return sessao_unica

    modelo = ambiente.get("MODEL_ARMOR_MODELO")
    regiao = ambiente.get("MODEL_ARMOR_REGIAO")
    configuracao = ambiente.get("RANKING_CONFIG")
    ligado_ao_armor = bool(modelo and regiao)
    return AdaptadoresDaBusca(
        transporte_da_consulta=(
            TransporteVertex(projeto, sessao_http()) if ligado_ao_armor else None
        ),
        armor=(
            ModelArmorReal(projeto, cast(str, regiao), cast(str, modelo), sessao_http())
            if ligado_ao_armor
            else None
        ),
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
