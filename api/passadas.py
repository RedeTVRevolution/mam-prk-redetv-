"""Passada de comparação (#247): a análise inteira de um Job concluído com outro modelo.

`make passada-de-comparacao JOB=... MODELO=...` roda no computador de quem executa, com
as credenciais dela, a mesma análise do Job (janelas, consolidação, identificação, com a
transcrição e a leitura da tela que ele já tem), sem escalonamento, e grava o resultado
como uma passada à parte, com o modelo, a data, o custo e o tempo de cada etapa.

A passada não é um Job nem uma Decupagem: mora em `<job>/passadas/<id>.json` no bucket
das decupagens, fora do índice da busca, do Acervo, das correções e do webhook (a função
`rodar_passada` nem recebe essas portas), e a Decupagem do Job nunca é regravada. O
catálogo de pessoas é lido de uma cópia: a identificação não acrescenta nome nele.
As rotas de leitura são para a tela lado a lado (#249).

Vem do ambiente (o Makefile lê os nomes do Terraform): `GCP_PROJECT_ID`, `BUCKET_ACEITOS`,
`BUCKET_DECUPAGENS`, `PRECOS_DOS_MODELOS` (`modelo=entrada:saida`, US$ por milhão de
tokens) e, opcional, `JANELAS_EM_PARALELO`.
"""

import os
import re
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Any, Protocol, cast

import google.auth
from fastapi import APIRouter, Depends, HTTPException, Path
from google.api_core.exceptions import NotFound
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore
from google.cloud.storage import Client as ClienteStorage
from pydantic import BaseModel

from api.analise_por_janelas import analisar_video
from api.auth import Chamador
from api.catalogo import Catalogo, CatalogoEmMemoria
from api.comparar_objetos import (
    FaltaNoAmbiente,
    Preco,
    exigir_do_ambiente,
    precos_do_ambiente,
    tokens_do_transporte,
)
from api.decupagem import Decupagem, Video
from api.gemini import AnaliseFalhou, SessaoHttp, Transporte, TransporteVertex
from api.jobs import (
    RepositorioDeJobs,
    _enxerga,
    _exige,
    agora_utc,
)
from api.leitura_da_tela import LeituraDaTela
from api.nuvem import (
    CatalogoFirestore,
    LeiturasStorage,
    RepositorioFirestore,
    TranscricoesStorage,
    objeto_do_proxy,
)
from api.transcricao import Transcricao

ETAPA_DE_CUSTO = "passada_de_comparacao"  # o rótulo de custo de cada chamada
# O id da passada leva o nome do modelo e vira nome de objeto e trecho da rota: sem barra.
FORMA_DO_ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


class JobNaoConcluido(Exception):
    pass


class Etapa(BaseModel):
    nome: str
    segundos: float


class Custo(BaseModel):
    tokens_de_entrada: int
    tokens_de_saida: int
    preco_por_milhao_de_entrada: float
    preco_por_milhao_de_saida: float
    usd: float


class ResumoDaPassada(BaseModel):
    id: str
    job_id: str
    modelo: str
    criada_em: datetime
    custo: Custo
    etapas: list[Etapa]


class Passada(ResumoDaPassada):
    decupagem: Decupagem

    def resumo(self) -> ResumoDaPassada:
        return ResumoDaPassada.model_validate(self.model_dump(exclude={"decupagem"}))


class LeituraDePassadas(Protocol):
    def ler_passada(self, job_id: str, passada_id: str) -> Passada | None: ...

    def listar_passadas(self, job_id: str) -> list[ResumoDaPassada]: ...


class ArmazemDaPassada(LeituraDePassadas, Protocol):
    """Do que a passada lê do Job (o proxy, a transcrição e a leitura da tela) e onde grava."""

    def uri_do_proxy(self, job_id: str) -> str: ...

    def ler_transcricao(self, job_id: str) -> Transcricao | None: ...

    def ler_leitura(self, job_id: str) -> LeituraDaTela | None: ...

    def gravar_passada(self, passada: Passada) -> None: ...


class PassadasEmMemoria:
    """Dublê do Storage."""

    def __init__(self) -> None:
        self.passadas: dict[tuple[str, str], Passada] = {}
        self.transcricoes: dict[str, Transcricao] = {}
        self.leituras: dict[str, LeituraDaTela] = {}

    def uri_do_proxy(self, job_id: str) -> str:
        return f"gs://aceitos/{job_id}/proxy.mp4"

    def ler_transcricao(self, job_id: str) -> Transcricao | None:
        return self.transcricoes.get(job_id)

    def ler_leitura(self, job_id: str) -> LeituraDaTela | None:
        return self.leituras.get(job_id)

    def gravar_passada(self, passada: Passada) -> None:
        self.passadas[(passada.job_id, passada.id)] = passada

    def ler_passada(self, job_id: str, passada_id: str) -> Passada | None:
        return self.passadas.get((job_id, passada_id))

    def listar_passadas(self, job_id: str) -> list[ResumoDaPassada]:
        return sorted(
            (p.resumo() for (j, _), p in self.passadas.items() if j == job_id),
            key=lambda r: r.criada_em,
        )


def preco_do_modelo(modelo: str, texto: str) -> Preco:
    """O preço do modelo em `PRECOS_DOS_MODELOS`; sem ele a passada nem começa."""
    precos = precos_do_ambiente(texto)
    if modelo not in precos:
        raise FaltaNoAmbiente(f"sem preço em PRECOS_DOS_MODELOS para {modelo}")
    return precos[modelo]


def rodar_passada(
    job_id: str,
    modelo: str,
    preco: Preco,
    *,
    repositorio: RepositorioDeJobs,
    armazem: ArmazemDaPassada,
    transporte: Transporte,
    catalogo: Catalogo | None = None,
    max_paralelas: int = 1,
    relogio: Callable[[], float] = time.monotonic,
    agora: Callable[[], datetime] = agora_utc,
    dormir: Callable[[float], None] = time.sleep,
) -> Passada:
    """Levanta `JobNaoConcluido` (o Job não existe ou não terminou) e `AnaliseFalhou`;
    `ValueError` para o modelo que não cabe no id da passada (`publishers/...`)."""
    if not re.fullmatch(FORMA_DO_ID, modelo):
        raise ValueError(f"modelo {modelo!r}: só o nome curto, sem barra")
    job = repositorio.obter(job_id)
    if job is None or job.estado != "concluido":
        raise JobNaoConcluido(f"O Job {job_id} não está concluído.")
    if job.sha256 is None or job.duracao_s is None:
        raise JobNaoConcluido(f"O Job {job_id} não tem vídeo analisado.")
    etapas: list[Etapa] = []

    @contextmanager
    def etapa(nome: str) -> Iterator[None]:
        inicio = relogio()
        yield
        etapas.append(Etapa(nome=nome, segundos=round(relogio() - inicio, 2)))

    entrada_antes, saida_antes = tokens_do_transporte(transporte)
    decupagem = analisar_video(
        transporte,
        video_uri=armazem.uri_do_proxy(job.id),
        job_id=job.id,
        programa=job.programa,
        cortes_ms=job.cortes_ms or (),
        video=Video(
            sha256=job.sha256,
            duracao_ms=round(job.duracao_s * 1000),
            timecode_origem=job.timecode_origem,
        ),
        transcricao=armazem.ler_transcricao(job.id),
        leitura=armazem.ler_leitura(job.id),
        max_paralelas=max_paralelas,
        catalogo=CatalogoEmMemoria.copia_de(catalogo) if catalogo else None,
        modelo=modelo,
        etapa_de_custo=ETAPA_DE_CUSTO,
        etapa=etapa,
        dormir=dormir,
    )
    entrada, saida = tokens_do_transporte(transporte)
    entrada -= entrada_antes
    saida -= saida_antes
    criada_em = agora()
    passada = Passada(
        id=f"{criada_em:%Y%m%dT%H%M%S}-{modelo}",
        job_id=job.id,
        modelo=modelo,
        criada_em=criada_em,
        custo=Custo(
            tokens_de_entrada=entrada,
            tokens_de_saida=saida,
            preco_por_milhao_de_entrada=preco.entrada,
            preco_por_milhao_de_saida=preco.saida,
            usd=round(entrada * preco.entrada / 1e6 + saida * preco.saida / 1e6, 6),
        ),
        etapas=etapas,
        decupagem=decupagem,
    )
    armazem.gravar_passada(passada)
    return passada


def prefixo_das_passadas(job_id: str) -> str:
    return f"{job_id}/passadas/"


def objeto_da_passada(job_id: str, passada_id: str) -> str:
    return f"{prefixo_das_passadas(job_id)}{passada_id}.json"


class PassadasStorage:
    """As passadas de comparação (#247), no bucket das decupagens, e o que elas leem do
    Job: o proxy, a transcrição e a leitura da tela, no bucket de aceitos. Nunca grava
    a Decupagem do Job."""

    def __init__(
        self, cliente: ClienteStorage, bucket_de_aceitos: str, bucket_de_decupagens: str
    ) -> None:
        self._cliente = cliente
        self._bucket_de_aceitos = bucket_de_aceitos
        self._aceitos = TranscricoesStorage(cliente, bucket_de_aceitos)
        self._leituras = LeiturasStorage(cliente, bucket_de_aceitos)
        self._decupagens = bucket_de_decupagens

    def uri_do_proxy(self, job_id: str) -> str:
        return f"gs://{self._bucket_de_aceitos}/{objeto_do_proxy(job_id)}"

    def ler_transcricao(self, job_id: str) -> Transcricao | None:
        return self._aceitos.ler_transcricao(job_id)

    def ler_leitura(self, job_id: str) -> LeituraDaTela | None:
        return self._leituras.ler_leitura(job_id)

    def gravar_passada(self, passada: Passada) -> None:
        self._cliente.bucket(self._decupagens).blob(
            objeto_da_passada(passada.job_id, passada.id)
        ).upload_from_string(passada.model_dump_json(), content_type="application/json")

    def ler_passada(self, job_id: str, passada_id: str) -> Passada | None:
        blob = self._cliente.bucket(self._decupagens).blob(
            objeto_da_passada(job_id, passada_id)
        )
        try:
            return Passada.model_validate_json(blob.download_as_bytes())
        except NotFound:
            return None

    def listar_passadas(self, job_id: str) -> list[ResumoDaPassada]:
        blobs = self._cliente.list_blobs(
            self._decupagens, prefix=prefixo_das_passadas(job_id)
        )
        resumos = [
            Passada.model_validate_json(b.download_as_bytes()).resumo() for b in blobs
        ]
        return sorted(resumos, key=lambda r: r.criada_em)


def criar_rotas_das_passadas(
    repositorio: RepositorioDeJobs, passadas: LeituraDePassadas
) -> APIRouter:
    """Só leitura, com `decupagem.ver`; a passada não recebe correções."""
    rotas = APIRouter(prefix="/jobs")

    @rotas.get("/{job_id}/passadas")
    def listar(
        job_id: str, chamador: Annotated[Chamador, Depends(_exige("ler"))]
    ) -> list[ResumoDaPassada]:
        job = _enxerga(chamador, repositorio.obter(job_id))
        return passadas.listar_passadas(job.id)

    @rotas.get("/{job_id}/passadas/{passada_id}")
    def ler(
        job_id: str,
        passada_id: Annotated[str, Path(pattern=FORMA_DO_ID)],
        chamador: Annotated[Chamador, Depends(_exige("ler"))],
    ) -> Passada:
        job = _enxerga(chamador, repositorio.obter(job_id))
        passada = passadas.ler_passada(job.id, passada_id)
        if passada is None:
            raise HTTPException(404, "Passada não encontrada")
        return passada

    return rotas


def main(argumentos: list[str], ambiente: Mapping[str, str] = os.environ) -> int:
    if len(argumentos) != 2:
        print("uso: python -m api.passadas JOB_ID MODELO", file=sys.stderr)
        return 2
    job_id, modelo = argumentos
    try:
        projeto = exigir_do_ambiente(ambiente, "GCP_PROJECT_ID")
        aceitos = exigir_do_ambiente(ambiente, "BUCKET_ACEITOS")
        decupagens = exigir_do_ambiente(ambiente, "BUCKET_DECUPAGENS")
        preco = preco_do_modelo(
            modelo, exigir_do_ambiente(ambiente, "PRECOS_DOS_MODELOS")
        )
        paralelas = int(ambiente.get("JANELAS_EM_PARALELO") or 1)
    except (FaltaNoAmbiente, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    credenciais: Any
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = cast(SessaoHttp, AuthorizedSession(credenciais))  # type: ignore[no-untyped-call]
    banco = firestore.Client(project=projeto)
    try:
        passada = rodar_passada(
            job_id,
            modelo,
            preco,
            repositorio=RepositorioFirestore(banco),
            armazem=PassadasStorage(
                ClienteStorage(project=projeto), aceitos, decupagens
            ),
            transporte=TransporteVertex(projeto, sessao),
            catalogo=CatalogoFirestore(banco),
            max_paralelas=paralelas,
        )
    except (JobNaoConcluido, AnaliseFalhou, ValueError) as e:
        print(f"erro: {e or 'a análise falhou'}", file=sys.stderr)
        return 1
    print(f"passada {passada.id} gravada")
    print(f"custo=US${passada.custo.usd:.4f} para o vídeo de {_hms(passada)}")
    for etapa in passada.etapas:
        print(f"{etapa.nome:14} {etapa.segundos}s")
    return 0


def _hms(passada: Passada) -> str:
    segundos = passada.decupagem.video.duracao_ms // 1000
    return f"{segundos // 3600}h{segundos % 3600 // 60:02d}min"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
