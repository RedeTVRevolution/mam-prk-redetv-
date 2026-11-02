"""A rota das fotos de referência de um nome (#163): dado sensível, só com `decupagem.ver`."""

import json
from typing import Any

from fastapi.testclient import TestClient

from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_jobs import (
    AUTORIZACAO,
    INICIO,
    ArmazenamentoFalso,
    VerificadorFalso,
)

ROTA = "/v1/jobs/j1/pessoas/p1/referencias"


def _foto(n: int, pagina: str) -> dict[str, Any]:
    return {
        "origem": "web",
        "referencia": f"referencias/c1/f{n}.jpg",
        "pagina_url": pagina,
        "imagem_url": f"https://img.exemplo/{n}.jpg",
        "busca": "ana",
        "obtida_em": None,
    }


VEREDITO = {
    "pessoas": ["p1", "p2"],
    "estado": "confirmado",
    "palpite": None,
    "palpite_descartado": False,
    "nome": "Ana",
    "escolhido": "Ana",
    "confiancas": [0.9, 0.9, 0.4],
    "fotos": [
        _foto(0, "https://www.exemplo.com.br/a/b?x=1"),
        _foto(1, "http://noticias.exemplo.org/z"),
        _foto(2, "javascript:alert(1)"),
    ],
    "conferem": [True, True, False],
}


def _mundo(
    papeis: RepositorioDePapeisEmMemoria | None = None,
    vereditos: list[Any] | None = None,
) -> tuple[TestClient, ArmazenamentoFalso]:
    repositorio = RepositorioEmMemoria()
    armazenamento = ArmazenamentoFalso()
    cliente = TestClient(
        criar_app(VerificadorFalso(), repositorio, armazenamento, papeis=papeis)
    )
    repositorio.salvar(
        Job(
            id="j1", nome="a.mp4", tamanho_bytes=10, estado="concluido",
            criado_por="u1", criado_em=INICIO, atualizado_em=INICIO,
        )
    )  # fmt: skip
    if vereditos is None:
        vereditos = [VEREDITO]
    armazenamento.comparacoes["j1"] = json.dumps(vereditos).encode()
    return cliente, armazenamento


def test_devolve_as_fotos_assinadas_com_pagina_dominio_e_resultado_em_palavras() -> (
    None
):
    cliente, _ = _mundo()

    resposta = cliente.get(ROTA, headers=AUTORIZACAO)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [f["url"] for f in corpo["fotos"]] == [
        f"https://storage.exemplo/fotos/referencias/c1/f{n}.jpg?validade=300"
        for n in range(3)
    ]
    assert [f["resultado"] for f in corpo["fotos"]] == [
        "confere",
        "confere",
        "nao_confere",
    ]
    assert [f["dominio"] for f in corpo["fotos"]] == [
        "exemplo.com.br",
        "noticias.exemplo.org",
        "",
    ]
    # Só endereço web vira link: nunca `javascript:`.
    assert [f["pagina_url"] for f in corpo["fotos"]] == [
        "https://www.exemplo.com.br/a/b?x=1",
        "http://noticias.exemplo.org/z",
        "",
    ]
    assert "porcentagem" not in resposta.text and "confianca" not in resposta.text


def test_foto_nao_vai_para_cache_publico() -> None:
    cliente, _ = _mundo()

    cache = cliente.get(ROTA, headers=AUTORIZACAO).headers["cache-control"]

    assert "no-store" in cache and "private" in cache


def test_as_fotos_exigem_decupagem_ver() -> None:
    papeis = RepositorioDePapeisEmMemoria()
    papeis.salvar("u1", [])
    cliente, _ = _mundo(papeis)

    resposta = cliente.get(ROTA, headers=AUTORIZACAO)

    assert resposta.status_code == 403
    assert "referencias/" not in resposta.text


def test_sem_login_e_401() -> None:
    cliente, _ = _mundo()

    assert cliente.get(ROTA).status_code == 401


def test_pessoa_sem_comparacao_ou_job_sem_ela_e_404() -> None:
    cliente, armazenamento = _mundo()
    assert (
        cliente.get(
            "/v1/jobs/j1/pessoas/p9/referencias", headers=AUTORIZACAO
        ).status_code
        == 404
    )
    del armazenamento.comparacoes["j1"]
    assert cliente.get(ROTA, headers=AUTORIZACAO).status_code == 404


def test_veredito_gravado_antes_do_campo_conferem_nao_diz_resultado() -> None:
    antigo = {k: v for k, v in VEREDITO.items() if k != "conferem"}
    cliente, _ = _mundo(vereditos=[antigo])

    fotos = cliente.get(ROTA, headers=AUTORIZACAO).json()["fotos"]

    assert [f["resultado"] for f in fotos] == [None, None, None]


def test_objeto_fora_de_referencias_nao_e_assinado() -> None:
    fora = {
        **VEREDITO,
        "fotos": [{**_foto(0, "https://a.com"), "referencia": "../j2/proxy.mp4"}],
    }
    cliente, _ = _mundo(vereditos=[fora])

    corpo = cliente.get(ROTA, headers=AUTORIZACAO).json()

    assert corpo["fotos"] == []
