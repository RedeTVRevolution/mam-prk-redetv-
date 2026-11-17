"""Cofre dos segredos do webhook no Secret Manager, com chave CMEK (#705).

Um segredo só, criado pelo Terraform (`WEBHOOK_SEGREDOS`), guarda o mapa
`{sistema: segredo}` em JSON; registrar um sistema grava uma versão nova com o mapa
inteiro. A web só lê (`secretAccessor`); quem registra roda `make registrar-webhook`.
"""

import base64
import json
from collections.abc import Callable, Mapping
from typing import Any

from api.clientes_de_nuvem import TransporteRest, transporte_rest
from api.erros import ServicoIndisponivel

URL_BASE = "https://secretmanager.googleapis.com/v1"
# Cabe no prazo da entrega (ack de 60 s), junto do Firestore e do POST.
TEMPO_DO_COFRE_S = 10.0


class ErroDoCofre(ServicoIndisponivel):
    """O Secret Manager não respondeu: 503, e o Pub/Sub tenta de novo. Nunca vira
    "sem segredo", que descarta o evento."""


def transporte_do_cofre() -> TransporteRest:
    return transporte_rest(URL_BASE, timeout_s=TEMPO_DO_COFRE_S)


class CofreSecretManager:
    # ponytail: dois registros ao mesmo tempo podem se sobrescrever no mapa; o registro
    # é manual e raro. Versões antigas guardam segredos trocados: desligue-as à mão.
    def __init__(self, segredo: str, transporte: TransporteRest) -> None:
        # `projects/<p>/secrets/<s>`
        self._segredo = segredo
        self._transporte = transporte

    def _chamar(
        self, metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        status, resposta = self._transporte(metodo, caminho, corpo)
        if status not in (200, 404):
            detalhe = resposta.get("error", {})
            raise ErroDoCofre(
                f"Secret Manager respondeu {status}: {detalhe.get('status', '')}".strip()
            )
        return status, resposta

    def _mapa(self) -> dict[str, str]:
        status, resposta = self._chamar(
            "GET", f"{self._segredo}/versions/latest:access", None
        )
        if status == 404:
            # Segredo ainda sem versão: nenhum sistema registrado.
            return {}
        mapa: dict[str, str] = json.loads(base64.b64decode(resposta["payload"]["data"]))
        return mapa

    def obter(self, sistema: str) -> str | None:
        return self._mapa().get(sistema)

    def guardar(self, sistema: str, segredo: str) -> None:
        dados = json.dumps(self._mapa() | {sistema: segredo}).encode()
        status, _ = self._chamar(
            "POST",
            f"{self._segredo}:addVersion",
            {"payload": {"data": base64.b64encode(dados).decode()}},
        )
        if status != 200:
            raise ErroDoCofre(f"Secret Manager respondeu {status} ao gravar")


def cofre_do_ambiente(
    ambiente: Mapping[str, str],
    transporte: Callable[[], TransporteRest] = transporte_do_cofre,
) -> CofreSecretManager | None:
    """Com `WEBHOOK_SEGREDOS` (o Terraform a define na web), o cofre do Secret Manager."""
    segredo = ambiente.get("WEBHOOK_SEGREDOS")
    return CofreSecretManager(segredo, transporte()) if segredo else None
