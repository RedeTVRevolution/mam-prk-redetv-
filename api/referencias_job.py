"""Cloud Run Job das referências de rosto pela web (#111, ADR 0005).

Único Job com internet (sem `vpc_access`), por isso só recebe nomes: `NOMES` (lista em
JSON) e, se houver, `PROGRAMA`. Nunca recebe quadros nem o vídeo. A chave do SerpAPI
fica no Secret Manager e só este Job a lê (`SEGREDO_DO_SERPAPI` é o nome do recurso, que
vem do Terraform). Um nome sem foto boa não derruba os outros; a busca que falha, sim,
termina a execução com erro.
"""

import base64
import json
import os
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, Protocol, cast

import google.auth
import requests
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage

from api.catalogo import Catalogo
from api.gemini import SessaoHttp, TransporteVertex
from api.imagens_hostis import SessaoDeDownload, baixar_original, baixar_thumbnail
from api.jobs import agora_utc
from api.nuvem import CatalogoFirestore, ReferenciasStorage, SugestoesFirestore
from api.referencias import (
    Armazenamento,
    Conferidor,
    ConferidorGemini,
    ExtratorDeNomes,
    ExtratorGemini,
    Resultado,
    Sugestoes,
    foto_baixada,
    referenciar,
    sugerir_apresentadores,
)
from api.serpapi import Busca, SerpApi

VALIDADE_PADRAO_DIAS = 180


def executar(
    nomes: Sequence[str],
    programa: str | None,
    *,
    catalogo: Catalogo,
    busca: Busca,
    baixar_thumbnail_de: Callable[[str], bytes],
    baixar_original_de: Callable[[str], bytes],
    conferidor: Conferidor,
    extrator: ExtratorDeNomes,
    armazenamento: Armazenamento,
    sugestoes: Sugestoes,
    validade: timedelta,
    agora: datetime,
) -> dict[str, Resultado]:
    """O resultado de cada nome; as sugestões de apresentadores só com `programa`."""
    baixar = foto_baixada(baixar_thumbnail_de, baixar_original_de)
    resultados = {
        nome: referenciar(
            nome,
            catalogo=catalogo,
            busca=busca,
            baixar=baixar,
            conferidor=conferidor,
            armazenamento=armazenamento,
            agora=agora,
            validade=validade,
        )
        for nome in nomes
    }
    if programa:
        sugerir_apresentadores(
            programa, busca=busca, extrator=extrator, sugestoes=sugestoes, agora=agora
        )
    return resultados


class SessaoDoSegredo(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


def ler_segredo(sessao: SessaoDoSegredo, recurso: str) -> str:
    """A última versão do segredo, pela API REST do Secret Manager."""
    resposta = sessao.get(
        f"https://secretmanager.googleapis.com/v1/{recurso}/versions/latest:access"
    )
    resposta.raise_for_status()
    return base64.b64decode(resposta.json()["payload"]["data"]).decode().strip()


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    nomes = json.loads(os.environ["NOMES"])
    if not isinstance(nomes, list) or not all(isinstance(n, str) for n in nomes):
        raise SystemExit("NOMES precisa ser uma lista de nomes em JSON")
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]
    chave = ler_segredo(cast(SessaoDoSegredo, sessao), os.environ["SEGREDO_DO_SERPAPI"])
    transporte = TransporteVertex(projeto, cast(SessaoHttp, sessao))
    job_id = os.environ.get("CLOUD_RUN_EXECUTION", "referencias")
    web = requests.Session()
    executar(
        nomes,
        os.environ.get("PROGRAMA") or None,
        catalogo=CatalogoFirestore(firestore.Client(project=projeto)),
        busca=SerpApi(chave),
        baixar_thumbnail_de=lambda url: baixar_thumbnail(
            url, cast(SessaoDeDownload, web)
        ),
        baixar_original_de=lambda url: baixar_original(
            url, cast(SessaoDeDownload, web)
        ),
        conferidor=ConferidorGemini(transporte, job_id),
        extrator=ExtratorGemini(transporte, job_id),
        armazenamento=ReferenciasStorage(
            ClienteStorage(project=projeto), os.environ["BUCKET_REFERENCIAS"]
        ),
        sugestoes=SugestoesFirestore(firestore.Client(project=projeto)),
        validade=timedelta(
            days=int(
                os.environ.get("VALIDADE_DAS_REFERENCIAS_DIAS", VALIDADE_PADRAO_DIAS)
            )
        ),
        agora=agora_utc(),
    )


if __name__ == "__main__":
    main()
