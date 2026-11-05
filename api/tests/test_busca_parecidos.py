"""Planos parecidos com este (#271): o vetor do quadro já indexado, sem enviar imagem."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from api.busca import PlanoSemVetor
from api.tests.test_busca import (
    AUTORIZACAO,
    EmbeddingDeTexto,
    Mundo,
    cliente,
    job,
    plano,
)

ROTA = "/v1/busca/parecidos"


def com_planos() -> tuple[TestClient, EmbeddingDeTexto]:
    embedding = EmbeddingDeTexto([0.0, 0.0])
    c, m = cliente(["consulta"], embedding_da_consulta=embedding)
    m.com(
        job("j1"),
        plano("j1:plano:1", [1.0, 0.0], "rua escura"),
        plano("j1:plano:2", [0.9, 0.1], "rua molhada"),
        plano("j1:plano:3", [0.1, 1.0], "estúdio"),
        plano("j1:plano:4", None, "sem vetor"),
    )
    return c, embedding


def inicios(r: dict) -> list[int]:  # type: ignore[type-arg]
    return [mo["inicio_ms"] for v in r["videos"] for mo in v["momentos"]]


def test_os_vizinhos_vem_pelo_vetor_e_o_proprio_plano_fica_de_fora() -> None:
    c, embedding = com_planos()

    r = c.get(ROTA, params={"job": "j1", "plano": 1}, headers=AUTORIZACAO)

    assert r.status_code == 200
    corpo = r.json()
    assert inicios(corpo) == [20_000, 30_000]
    assert corpo["entendida"]["visual"] is True
    # Nenhuma imagem nem texto vai ao embedding: o vetor já estava no índice.
    assert embedding.imagens == [] and embedding.textos == []


def test_plano_sem_vetor_responde_404_com_mensagem_clara() -> None:
    c, _ = com_planos()

    r = c.get(ROTA, params={"job": "j1", "plano": 4}, headers=AUTORIZACAO)

    assert r.status_code == 404
    assert "vetor" in r.json()["detail"]


def test_plano_que_nao_existe_responde_404() -> None:
    c, _ = com_planos()
    r = c.get(ROTA, params={"job": "j1", "plano": 9}, headers=AUTORIZACAO)
    assert r.status_code == 404


def test_video_que_nao_existe_responde_404_e_nao_lista_planos() -> None:
    c, _ = com_planos()
    r = c.get(ROTA, params={"job": "zz", "plano": 1}, headers=AUTORIZACAO)
    assert r.status_code == 404
    assert "não foi encontrado" in r.json()["detail"]
    r = c.get(f"{ROTA}/planos", params={"job": "zz"}, headers=AUTORIZACAO)
    assert r.json() == {"planos": []}


@pytest.mark.parametrize(
    ("mudancas", "sistema"),
    [({"estado": "analisando"}, None), ({"sistema": "legado"}, "outro")],
    ids=["fora-de-concluido", "de-outro-sistema"],
)
def test_video_que_o_chamador_nao_ve_nao_da_vetor_nem_vizinhos(
    mudancas: dict[str, str], sistema: str | None
) -> None:
    m = Mundo()
    m.com(
        job("j1", **mudancas),
        plano("j1:plano:1", [1.0, 0.0]),
        plano("j1:plano:2", [0.9, 0.1]),
    )
    busca = m.busca()

    assert busca.planos_com_vetor("j1", sistema) == {}
    with pytest.raises(PlanoSemVetor):
        busca.buscar_parecidos("j1", 1, sistema=sistema)


def test_chave_do_mesmo_sistema_ve_os_vizinhos() -> None:
    m = Mundo()
    m.com(
        job("j1", sistema="outro"),
        plano("j1:plano:1", [1.0, 0.0]),
        plano("j1:plano:2", [0.9, 0.1]),
    )

    r = m.busca().buscar_parecidos("j1", 1, sistema="outro")

    assert [mo.inicio_ms for v in r.videos for mo in v.momentos] == [20_000]


def test_sem_permissao_de_leitura_responde_403() -> None:
    embedding = EmbeddingDeTexto([0.0, 0.0])
    c, _ = cliente([], embedding_da_consulta=embedding)
    r = c.get(ROTA, params={"job": "j1", "plano": 1}, headers=AUTORIZACAO)
    assert r.status_code == 403


def test_a_lista_dos_planos_com_vetor_do_video() -> None:
    c, _ = com_planos()

    r = c.get(f"{ROTA}/planos", params={"job": "j1"}, headers=AUTORIZACAO)

    assert r.status_code == 200
    assert r.json() == {"planos": [1, 2, 3]}


def test_os_parecidos_vem_em_paginas_por_cursor_e_cursor_invalido_da_422() -> None:
    c, m = cliente(["consulta"], embedding_da_consulta=EmbeddingDeTexto([0.0, 0.0]))
    m.com(job("j1"), plano("j1:plano:1", [1.0, 0.0]))
    for j in ("j2", "j3"):
        m.com(job(j), replace(plano(f"{j}:plano:1", [0.9, 0.1]), job_id=j))
    params: dict[str, str | int] = {"job": "j1", "plano": 1, "limite": 1}

    r1 = c.get(ROTA, params=params, headers=AUTORIZACAO)
    cursor = r1.headers["X-Proximo-Cursor"]
    r2 = c.get(ROTA, params=params | {"cursor": cursor}, headers=AUTORIZACAO)
    ruim = c.get(ROTA, params=params | {"cursor": "nao-existe"}, headers=AUTORIZACAO)

    videos = [r.json()["videos"][0]["job_id"] for r in (r1, r2)]
    assert sorted(videos) == ["j2", "j3"]
    assert "X-Proximo-Cursor" not in r2.headers
    assert ruim.status_code == 422
