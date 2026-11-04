"""Teste de caos no dev (E7, #274): `make caos-dev`.

Roda o mesmo roteiro do teste local (`api.caos.roteiro`) contra a API no ar, por HTTP, com
as chaves de dois sistemas de teste. Variáveis: `URL` (a API), `CHAVE_A` e `CHAVE_B`
(emitidas com `make emitir-chave`, escopos criar, ler e cancelar) e, se quiser, `CLIPE`
(um MP4 de verdade, enviado pelo upload retomável de um dos Jobs, e esperado até o fim
do pipeline: isso gasta Gemini e GPU, então só com `CLIPE=` explícito).
Sai com 0 se tudo passou, 1 se algo falhou e 2 se faltou configuração.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

from api.caos import CORPO, Relatorio, roteiro

ESTADOS_FINAIS = {"concluido", "falhou", "rejeitado", "cancelado"}
ESPERA_MAXIMA_S = 3600


class ApiNoAr:
    def __init__(self, url: str, chaves: dict[str, str]) -> None:
        self._url = url.rstrip("/")
        self._chaves = chaves

    def requisitar(
        self,
        metodo: str,
        caminho: str,
        *,
        sistema: str,
        corpo: dict[str, Any] | None = None,
        chave: str | None = None,
    ) -> tuple[int, Any]:
        cabecalhos = {"X-API-Key": self._chaves[sistema]}
        if chave is not None:
            cabecalhos["Idempotency-Key"] = chave
        resposta = requests.request(
            metodo,
            f"{self._url}/v1{caminho}",
            json=corpo,
            headers=cabecalhos,
            timeout=30,
        )
        try:
            return resposta.status_code, resposta.json()
        except ValueError:
            return resposta.status_code, None


def enviar_clipe(api: ApiNoAr, sistema: str, clipe: Path) -> Relatorio:
    """Cria um Job com o clipe, envia pelo upload retomável e espera o fim do pipeline."""
    relatorio = Relatorio()
    dados = clipe.read_bytes()
    corpo: dict[str, Any] = {
        "nome": clipe.name,
        "tamanho_bytes": len(dados),
        "tipo": CORPO["tipo"],
    }
    status, job = api.requisitar("POST", "/jobs", sistema=sistema, corpo=corpo)
    if status != 202:
        relatorio.conferir("clipe: cria o Job", False, f"{status} {job}")
        return relatorio
    sessao = requests.post(
        job["url_de_upload"],
        headers={
            "Content-Type": str(corpo["tipo"]),
            "x-goog-resumable": "start",
            "x-upload-content-length": str(len(dados)),
        },
        timeout=60,
    )
    destino = sessao.headers.get("Location")
    if sessao.status_code not in (200, 201) or not destino:
        relatorio.conferir("clipe: abre o upload", False, str(sessao.status_code))
        return relatorio
    enviado = requests.put(destino, data=dados, timeout=600)
    relatorio.conferir(
        "clipe: envia o arquivo",
        enviado.status_code in (200, 201),
        str(enviado.status_code),
    )
    estado = ""
    limite = time.monotonic() + ESPERA_MAXIMA_S
    while time.monotonic() < limite:
        _, lido = api.requisitar("GET", f"/jobs/{job['id']}", sistema=sistema)
        estado = (lido or {}).get("estado", "")
        if estado in ESTADOS_FINAIS:
            break
        time.sleep(15)
    relatorio.conferir(
        "clipe: o Job chega a concluido", estado == "concluido", f"estado {estado!r}"
    )
    return relatorio


def main() -> int:
    url, chave_a, chave_b = (os.environ.get(n) for n in ("URL", "CHAVE_A", "CHAVE_B"))
    if not (url and chave_a and chave_b):
        print(
            "Faltam URL, CHAVE_A e CHAVE_B (chaves de API de dois sistemas de teste, "
            "de make emitir-chave).",
            file=sys.stderr,
        )
        return 2
    api = ApiNoAr(url, {"A": chave_a, "B": chave_b})
    relatorio = roteiro(api, "A", "B")
    clipe = os.environ.get("CLIPE")
    if clipe:
        relatorio.verificacoes.extend(enviar_clipe(api, "A", Path(clipe)).verificacoes)
    print(relatorio.texto())
    return 0 if relatorio.passou else 1


if __name__ == "__main__":
    sys.exit(main())
