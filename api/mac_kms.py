"""Chave MAC do Cloud KMS para o hash das chaves de API (#272).

Implementa a porta `Mac` de `api.chaves` com `macSign` e `macVerify` na API REST do
KMS. A versão da chave vai no registro de cada chave de API, então a rotação é
manual: criar uma versão nova no KMS (README); a mais alta ativa passa a ser a atual.
"""

import base64
import hashlib
import time
import urllib.parse
from collections.abc import Callable, Mapping
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession

from api.cache_curto import CacheCurto
from api.chaves import Mac, MacSimulado
from api.jobs import ServicoIndisponivel

URL_BASE = "https://cloudkms.googleapis.com/v1"
# Quanto tempo a versão atual fica guardada: evita uma ida ao KMS por requisição.
VALIDADE_DA_VERSAO_S = 300.0
# Quanto tempo um `macVerify` positivo fica guardado (#491) e quantos cabem. A revogação
# não espera esse prazo: o registro da chave é lido em todo pedido.
VALIDADE_DO_MAC_S = 300.0
MAXIMO_DO_MAC = 1024

# (método, caminho a partir de /v1, corpo) -> (status HTTP, resposta em JSON)
Transporte = Callable[[str, str, dict[str, Any] | None], tuple[int, dict[str, Any]]]


class ErroDoKms(ServicoIndisponivel):
    """O KMS não respondeu como devia: a API devolve 503, não 500."""


def _erro(status: int, resposta: dict[str, Any]) -> ErroDoKms:
    detalhe = resposta.get("error", {})
    return ErroDoKms(
        f"Cloud KMS respondeu {status}: {detalhe.get('status', '')} {detalhe.get('message', '')}".strip()
    )


class _NaoConfere(Exception):
    """Faz o resultado negativo escapar do cache, que só guarda o positivo."""


class MacKms:
    def __init__(
        self,
        chave: str,
        transporte: Transporte,
        relogio: Callable[[], float] = time.monotonic,
        validade_s: float = VALIDADE_DA_VERSAO_S,
        validade_do_mac_s: float = VALIDADE_DO_MAC_S,
        maximo_do_mac: int = MAXIMO_DO_MAC,
    ) -> None:
        # `projects/<p>/locations/<l>/keyRings/<r>/cryptoKeys/<k>`
        self._chave = chave
        self._transporte = transporte
        self._relogio = relogio
        self._validade_s = validade_s
        self._versao: tuple[int, float] | None = None
        self._conferidos = CacheCurto(validade_do_mac_s, maximo_do_mac, relogio)

    @property
    def versao_atual(self) -> int:
        if self._versao and self._relogio() - self._versao[1] < self._validade_s:
            return self._versao[0]
        versoes: list[int] = []
        caminho = f"{self._chave}/cryptoKeyVersions"
        pagina = ""
        while True:
            status, resposta = self._transporte("GET", caminho + pagina, None)
            if status != 200:
                raise _erro(status, resposta)
            versoes += [
                int(v["name"].rsplit("/", 1)[1])
                for v in resposta.get("cryptoKeyVersions", [])
                if v.get("state") == "ENABLED"
            ]
            if not resposta.get("nextPageToken"):
                break
            pagina = "?pageToken=" + urllib.parse.quote(
                resposta["nextPageToken"], safe=""
            )
        if not versoes:
            raise ErroDoKms(f"a chave {self._chave} não tem versão ativa")
        self._versao = (max(versoes), self._relogio())
        return self._versao[0]

    def _pedir(
        self, versao: int, operacao: str, corpo: dict[str, Any]
    ) -> dict[str, Any]:
        caminho = f"{self._chave}/cryptoKeyVersions/{versao}:{operacao}"
        status, resposta = self._transporte("POST", caminho, corpo)
        erro = resposta.get("error", {}).get("status")
        # Versão que não existe, desligada ou destruída: a chave de API não vale.
        if status == 404 or erro == "FAILED_PRECONDITION":
            raise KeyError(versao)
        if status != 200:
            raise _erro(status, resposta)
        return resposta

    def calcular(self, versao: int, mensagem: bytes) -> bytes:
        resposta = self._pedir(
            versao, "macSign", {"data": base64.b64encode(mensagem).decode()}
        )
        return base64.b64decode(resposta["mac"])

    def verificar(self, versao: int, mensagem: bytes, mac: bytes) -> bool:
        """Só o positivo é guardado, por versão, hash da mensagem (o segredo nunca fica
        na memória) e MAC; segredo errado sempre vai ao KMS."""
        chave = (versao, hashlib.sha256(mensagem).digest(), mac)
        try:
            return self._conferidos.obter(
                chave, lambda: self._conferir(versao, mensagem, mac)
            )
        except _NaoConfere:
            return False

    def _conferir(self, versao: int, mensagem: bytes, mac: bytes) -> bool:
        resposta = self._pedir(
            versao,
            "macVerify",
            {
                "data": base64.b64encode(mensagem).decode(),
                "mac": base64.b64encode(mac).decode(),
            },
        )
        if not resposta.get("success"):
            raise _NaoConfere
        return True


def transporte_do_kms() -> Transporte:
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]

    def transporte(
        metodo: str, caminho: str, corpo: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        resposta = sessao.request(  # type: ignore[no-untyped-call]
            metodo, f"{URL_BASE}/{caminho}", json=corpo, timeout=30
        )
        try:
            return resposta.status_code, resposta.json()
        except ValueError:
            return resposta.status_code, {}

    return transporte


def mac_do_ambiente(
    ambiente: Mapping[str, str],
    transporte: Callable[[], Transporte] = transporte_do_kms,
) -> Mac | None:
    """Com `KMS_CHAVE_MAC` (o Terraform a define no Cloud Run), o Cloud KMS; sem ela,
    o simulado de `MAC_SIMULADO_CHAVE` (máquina local e emulador); sem as duas, nenhum."""
    if chave := ambiente.get("KMS_CHAVE_MAC"):
        return MacKms(chave, transporte())
    if simulada := ambiente.get("MAC_SIMULADO_CHAVE"):
        return MacSimulado({1: bytes.fromhex(simulada)}, versao_atual=1)
    return None
