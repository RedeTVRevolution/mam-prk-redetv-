"""Busca pelo SerpAPI (#111, ADR 0005): imagens (`engine=google_images`) e web
(`engine=google`). O formato lido é o da documentação do SerpAPI; a resposta real é
gravada na parte no ar.

A chave vai na query, como o SerpAPI pede: por isso um erro de rede nunca leva a
exceção original adiante (a mensagem do `requests` traz a URL com a chave).
"""

from dataclasses import dataclass
from typing import Any, Protocol, cast

import requests

URL = "https://serpapi.com/search.json"
PRAZO_DA_BUSCA_S = 30.0
# O que o SerpAPI põe em `error` (com HTTP 200) quando a busca deu certo e não achou nada.
SEM_RESULTADOS = "Google hasn't returned any results for this query."


class BuscaFalhou(Exception):
    """A busca não respondeu ou respondeu com erro."""


@dataclass(frozen=True)
class ResultadoDeImagem:
    thumbnail: str
    original: str
    pagina: str
    titulo: str


@dataclass(frozen=True)
class ResultadoWeb:
    titulo: str
    trecho: str
    link: str


class Busca(Protocol):
    def imagens(self, consulta: str) -> list[ResultadoDeImagem]: ...

    def web(self, consulta: str) -> list[ResultadoWeb]: ...


class SessaoDeBusca(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


def _texto(valor: Any) -> str:
    return valor if isinstance(valor, str) else ""


def imagens_da_resposta(dados: dict[str, Any]) -> list[ResultadoDeImagem]:
    """`images_results` do google_images: thumbnail, original, link (a página) e title."""
    achados = []
    for item in dados.get("images_results") or []:
        if not isinstance(item, dict):
            continue
        achados.append(
            ResultadoDeImagem(
                thumbnail=_texto(item.get("thumbnail")),
                original=_texto(item.get("original")),
                pagina=_texto(item.get("link")),
                titulo=_texto(item.get("title")),
            )
        )
    return [a for a in achados if a.thumbnail or a.original]


def web_da_resposta(dados: dict[str, Any]) -> list[ResultadoWeb]:
    """`organic_results` do google: title, snippet e link."""
    achados = []
    for item in dados.get("organic_results") or []:
        if isinstance(item, dict):
            achados.append(
                ResultadoWeb(
                    titulo=_texto(item.get("title")),
                    trecho=_texto(item.get("snippet")),
                    link=_texto(item.get("link")),
                )
            )
    return achados


class SerpApi:
    def __init__(self, chave: str, sessao: SessaoDeBusca | None = None) -> None:
        self._chave = chave
        self._sessao = sessao or cast(SessaoDeBusca, requests.Session())

    def _buscar(self, engine: str, consulta: str) -> dict[str, Any]:
        try:
            resposta = self._sessao.get(
                URL,
                params={"engine": engine, "q": consulta, "api_key": self._chave},
                timeout=PRAZO_DA_BUSCA_S,
            )
            if resposta.status_code != 200:
                raise BuscaFalhou(f"HTTP {resposta.status_code}")
            dados = resposta.json()
        except (requests.RequestException, OSError, ValueError):
            raise BuscaFalhou("falha de rede ou resposta que não é JSON") from None
        if not isinstance(dados, dict):
            raise BuscaFalhou("resposta que não é um objeto")
        if dados.get("error") and dados["error"] != SEM_RESULTADOS:
            raise BuscaFalhou("a busca respondeu com erro")
        return {} if dados.get("error") else dados

    def imagens(self, consulta: str) -> list[ResultadoDeImagem]:
        return imagens_da_resposta(self._buscar("google_images", consulta))

    def web(self, consulta: str) -> list[ResultadoWeb]:
        return web_da_resposta(self._buscar("google", consulta))
