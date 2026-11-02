"""Cloud Run Job das referências de rosto pela web (#111, ADR 0005).

Único Job com internet (sem `vpc_access`), por isso só recebe nomes: `NOMES` (lista em
JSON) e, se houver, `PROGRAMA`; ou `JOB_ID`, e a lista vem da identificação do vídeo.
Nunca recebe quadros nem o vídeo. A chave do SerpAPI fica no Secret Manager e só este
Job a lê (`SEGREDO_DO_SERPAPI` é o nome do recurso, que vem do Terraform). Um nome sem
foto boa não derruba os outros; a busca que falha, sim, termina a execução com erro.
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
from api.nuvem import (
    CatalogoFirestore,
    NomesABuscarStorage,
    ReferenciasStorage,
    SugestoesFirestore,
)
from api.referencias import (
    Armazenamento,
    BuscaComLimite,
    Conferidor,
    ConferidorGemini,
    ExtratorDeNomes,
    ExtratorGemini,
    LimiteDeBuscas,
    Resultado,
    Sugestoes,
    foto_baixada,
    referenciar,
    sugerir_apresentadores,
)
from api.rostos_dos_palpites import Palpites
from api.serpapi import Busca, SerpApi
from api.sinais import imprimir

VALIDADE_PADRAO_DIAS = 180
LIMITE_DE_BUSCAS_PADRAO = 12  # buscas no SerpAPI por vídeo


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
    palpites: Palpites,
    validade: timedelta,
    agora: datetime,
    limite_de_buscas: int = LIMITE_DE_BUSCAS_PADRAO,
    job_id: str = "referencias",
    registrar: Callable[[dict[str, str]], None] = lambda rotulo: None,
) -> dict[str, Resultado]:
    """O resultado de cada nome; as sugestões de apresentadores só com `programa`.

    Depois de `limite_de_buscas` buscas o vídeo não faz mais nenhuma: o nome que
    precisaria de busca fica `limite_de_buscas`. Cada busca vai a `registrar` com o
    rótulo de custo."""
    baixar = foto_baixada(baixar_thumbnail_de, baixar_original_de)
    contada = BuscaComLimite(busca, limite_de_buscas, registrar, job_id)
    resultados: dict[str, Resultado] = {}
    for nome in nomes:
        try:
            resultados[nome] = referenciar(
                nome,
                catalogo=catalogo,
                busca=contada,
                baixar=baixar,
                conferidor=conferidor,
                armazenamento=armazenamento,
                agora=agora,
                validade=validade,
                palpites=palpites,
            )
        except LimiteDeBuscas:
            resultados[nome] = "limite_de_buscas"
    if programa:
        try:
            sugerir_apresentadores(
                programa,
                busca=contada,
                extrator=extrator,
                sugestoes=sugestoes,
                agora=agora,
            )
        except LimiteDeBuscas:
            pass
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


def _nomes_do_job(
    job_id: str, leitor: NomesABuscarStorage
) -> tuple[list[str], str | None] | None:
    lista = leitor.ler_nomes_a_buscar(job_id)
    return None if lista is None else (lista.nomes, lista.programa)


def _registrar_o_custo(rotulo: dict[str, str]) -> None:
    print(json.dumps({"severity": "INFO", "message": "busca", **rotulo}), flush=True)


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    job_do_video = os.environ.get("JOB_ID")
    if job_do_video:
        achados = _nomes_do_job(
            job_do_video,
            NomesABuscarStorage(
                ClienteStorage(project=projeto), os.environ["BUCKET_DECUPAGENS"]
            ),
        )
        if achados is None:
            return  # a identificação não deixou lista: nada a buscar
        nomes, programa = achados
    else:
        nomes = json.loads(os.environ["NOMES"])
        if not isinstance(nomes, list) or not all(isinstance(n, str) for n in nomes):
            raise SystemExit("NOMES precisa ser uma lista de nomes em JSON")
        programa = os.environ.get("PROGRAMA") or None
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]
    chave = ler_segredo(cast(SessaoDoSegredo, sessao), os.environ["SEGREDO_DO_SERPAPI"])
    transporte = TransporteVertex(projeto, cast(SessaoHttp, sessao), imprimir)
    job_id = job_do_video or os.environ.get("CLOUD_RUN_EXECUTION", "referencias")
    web = requests.Session()
    armazenamento = ReferenciasStorage(
        ClienteStorage(project=projeto), os.environ["BUCKET_REFERENCIAS"]
    )
    executar(
        nomes,
        programa,
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
        armazenamento=armazenamento,
        sugestoes=SugestoesFirestore(firestore.Client(project=projeto)),
        palpites=Palpites(armazenamento),
        validade=timedelta(
            days=int(
                os.environ.get("VALIDADE_DAS_REFERENCIAS_DIAS", VALIDADE_PADRAO_DIAS)
            )
        ),
        agora=agora_utc(),
        limite_de_buscas=int(
            os.environ.get("LIMITE_DE_BUSCAS_POR_VIDEO", LIMITE_DE_BUSCAS_PADRAO)
        ),
        job_id=job_id,
        registrar=_registrar_o_custo,
    )


if __name__ == "__main__":
    main()
