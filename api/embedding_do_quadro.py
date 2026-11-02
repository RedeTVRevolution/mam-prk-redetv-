"""O vetor multimodal do quadro-chave de cada plano, para a busca por imagem (#268).

O Gemini Embedding 2 recebe o quadro (JPEG) e a descrição do plano e devolve um vetor só,
na dimensão da coleção. Só o registro de plano leva o vetor; sem quadro, ou se o quadro
não lê ou o embedding falha, o plano segue só com o vetor do texto (embedding automático
da coleção). A rede fica atrás de `Transporte`; os testes usam um dublê.
"""

import base64
import logging
import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any, Protocol

import google.auth
import google.auth.transport.requests

from api.agent_retrieval import ConfigDaBusca

log = logging.getLogger(__name__)

MODELO_DO_EMBEDDING_DO_QUADRO = "gemini-embedding-2"
# Endpoint global, como o Gemini da análise (ADR 0001).
URL_BASE = "https://aiplatform.googleapis.com/v1"
# Chamadas simultâneas por vídeo: a reindexação de uma Correção roda dentro do pedido HTTP,
# e 600 planos em série (uma hora de vídeo) passariam do tempo do Cloud Run.
CHAMADAS_SIMULTANEAS = 16

Transporte = Callable[[str, dict[str, Any]], dict[str, Any]]


class EmbeddingDoQuadro(Protocol):
    def vetor(self, jpeg: bytes, descricao: str) -> list[float]: ...


class GeminiEmbedding:
    def __init__(self, projeto: str, dimensao: int, transporte: Transporte) -> None:
        self._projeto = projeto
        self._dimensao = dimensao
        self._transporte = transporte

    def vetor(self, jpeg: bytes, descricao: str) -> list[float]:
        return self._embutir(
            [
                {"text": descricao},
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": base64.b64encode(jpeg).decode(),
                    }
                },
            ]
        )

    def vetor_do_texto(self, texto: str) -> list[float]:
        """O vetor da consulta de texto, no mesmo espaço dos vetores dos quadros (#269)."""
        return self._embutir([{"text": texto}])

    def _embutir(self, partes: list[dict[str, Any]]) -> list[float]:
        url = (
            f"{URL_BASE}/projects/{self._projeto}/locations/global/publishers/google/"
            f"models/{MODELO_DO_EMBEDDING_DO_QUADRO}:embedContent"
        )
        corpo = {
            "content": {"parts": partes},
            # O `outputDimensionality` no topo do pedido está obsoleto na API v1.
            "embedContentConfig": {"outputDimensionality": self._dimensao},
        }
        valores = [
            float(v) for v in self._transporte(url, corpo)["embedding"]["values"]
        ]
        if len(valores) != self._dimensao:
            raise ValueError(
                f"o embedding veio com dimensão {len(valores)}, e a coleção tem {self._dimensao}"
            )
        # O vetor reduzido já vem normalizado (documentação do Gemini Embedding 2); normalizar
        # de novo protege a distância de cosseno do índice se isso mudar.
        norma = math.sqrt(sum(v * v for v in valores))
        return [v / norma for v in valores] if norma else valores


def com_vetores_do_quadro(
    registros: list[Any],
    ler_quadro: Callable[[str], bytes],
    embedding: EmbeddingDoQuadro | None,
) -> list[Any]:
    """Os registros, com o vetor do quadro nos planos que têm quadro-chave."""
    if embedding is None:
        return registros

    def com_vetor(r: Any) -> Any:
        if not (r.tipo == "plano" and r.quadro and r.descricao):
            return r
        try:
            return replace(
                r, vetor_do_quadro=embedding.vetor(ler_quadro(r.quadro), r.descricao)
            )
        except Exception:
            log.exception("vetor do quadro não calculado para %s", r.id)
            return r

    with ThreadPoolExecutor(max_workers=CHAMADAS_SIMULTANEAS) as pool:
        return list(pool.map(com_vetor, registros))


def transporte_http() -> Transporte:
    """O transporte real: REST com as credenciais padrão (ADC) de quem roda."""
    credenciais, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    sessao = google.auth.transport.requests.AuthorizedSession(credenciais)  # type: ignore[no-untyped-call]

    def chamar(url: str, corpo: dict[str, Any]) -> dict[str, Any]:
        resposta = sessao.post(url, json=corpo, timeout=60)
        if not resposta.ok:
            raise RuntimeError(f"HTTP {resposta.status_code}: {resposta.text[:2000]}")
        return dict(resposta.json())

    return chamar


def embedding_da_busca(config: ConfigDaBusca | None) -> GeminiEmbedding | None:
    """`None` sem busca ou com o índice do quadro-chave desligado (ADR 0006)."""
    if config is None or config.indice_do_quadro is None:
        return None
    return GeminiEmbedding(config.projeto, config.dimensao, transporte_http())
