"""SerpAPI (#111): respostas montadas a partir do formato documentado."""

from typing import Any

import pytest
import requests

from api.serpapi import (
    SEM_RESULTADOS,
    BuscaFalhou,
    ResultadoDeImagem,
    SerpApi,
    imagens_da_resposta,
    web_da_resposta,
)

IMAGENS = {
    "search_metadata": {"status": "Success"},
    "images_results": [
        {
            "position": 1,
            "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:AAA",
            "source": "exemplo.com.br",
            "title": "Leão Lobo no estúdio",
            "link": "https://exemplo.com.br/leao",
            "original": "https://exemplo.com.br/fotos/leao.jpg",
            "original_width": 1200,
            "original_height": 800,
            "is_product": False,
        },
        {"position": 2, "title": "sem imagem", "link": "https://exemplo.com.br/x"},
        "lixo",
    ],
}
WEB = {
    "organic_results": [
        {
            "position": 1,
            "title": "TV Fama - RedeTV",
            "link": "https://redetv.uol.com.br/tvfama",
            "snippet": "Com Flávia Noronha e Leão Lobo.",
        }
    ]
}


class Resposta:
    def __init__(self, dados: Any, status: int = 200) -> None:
        self.dados = dados
        self.status_code = status

    def json(self) -> Any:
        if isinstance(self.dados, Exception):
            raise self.dados
        return self.dados


class Sessao:
    def __init__(self, resposta: Resposta | Exception) -> None:
        self.resposta = resposta
        self.pedidos: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> Resposta:
        self.pedidos.append({"url": url, **kwargs})
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


def test_imagens_trazem_thumbnail_original_pagina_e_titulo() -> None:
    assert imagens_da_resposta(IMAGENS) == [
        ResultadoDeImagem(
            thumbnail="https://encrypted-tbn0.gstatic.com/images?q=tbn:AAA",
            original="https://exemplo.com.br/fotos/leao.jpg",
            pagina="https://exemplo.com.br/leao",
            titulo="Leão Lobo no estúdio",
        )
    ]


def test_web_traz_titulo_trecho_e_link() -> None:
    [r] = web_da_resposta(WEB)

    assert (r.titulo, r.trecho, r.link) == (
        "TV Fama - RedeTV",
        "Com Flávia Noronha e Leão Lobo.",
        "https://redetv.uol.com.br/tvfama",
    )


def test_cada_busca_pede_o_engine_certo_com_a_chave() -> None:
    sessao = Sessao(Resposta(IMAGENS))
    SerpApi("chave-x", sessao).imagens("Leão Lobo")
    SerpApi("chave-x", Sessao(Resposta(WEB))).web("apresentadores TV Fama RedeTV")

    assert sessao.pedidos[0]["params"] == {
        "engine": "google_images",
        "q": "Leão Lobo",
        "api_key": "chave-x",
    }


def test_busca_web_usa_o_engine_google() -> None:
    sessao = Sessao(Resposta(WEB))
    SerpApi("c", sessao).web("q")

    assert sessao.pedidos[0]["params"]["engine"] == "google"


def test_sem_resultados_nao_e_falha() -> None:
    sessao = Sessao(Resposta({"error": SEM_RESULTADOS}))

    assert SerpApi("c", sessao).imagens("ninguém") == []


@pytest.mark.parametrize(
    "resposta",
    [
        Resposta({}, status=401),
        Resposta({"error": "Invalid API key."}),
        Resposta(ValueError("não é JSON")),
        Resposta(["lista"]),
        requests.ConnectionError("https://serpapi.com/?api_key=chave-secreta"),
    ],
)
def test_falha_da_busca_levanta_busca_falhou_sem_vazar_a_chave(
    resposta: Resposta | Exception,
) -> None:
    with pytest.raises(BuscaFalhou) as erro:
        SerpApi("chave-secreta", Sessao(resposta)).imagens("x")

    assert "chave-secreta" not in str(erro.value)
    assert erro.value.__cause__ is None
    assert erro.value.__context__ is None or erro.value.__suppress_context__
