"""O limite de buscas por minuto vem da configuração (#577); o padrão continua 30."""

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.eventos_de_uso import EventosEmMemoria
from api.rota_da_busca import (
    consultas_por_minuto_do_ambiente,
    paginas_por_minuto_do_ambiente,
)
from api.teste_de_carga import (
    CABECALHO_DE_TESTE,
    aceita_teste_de_carga_do_ambiente,
)
from api.tests.test_busca import AUTORIZACAO, cliente, job, objeto, pedido
from api.tests.test_busca_por_imagem import VESTIDO, enviar, foto


def _texto(c: Any) -> int:
    r = c.get("/v1/busca", params={"q": "vestido"}, headers=AUTORIZACAO)
    return int(r.status_code)


def test_com_o_padrao_a_31a_busca_do_minuto_volta_429() -> None:
    c, _ = cliente(["consulta"], *[pedido(texto_livre="vestido")] * 31)
    codigos = [_texto(c) for _ in range(31)]
    assert codigos == [200] * 30 + [429]


def test_texto_e_imagem_somam_no_mesmo_limite() -> None:
    c, _ = cliente(
        ["consulta"],
        *VESTIDO,
        pedido(texto_livre="vestido"),
        maximo_por_minuto=2,
    )
    assert enviar(c, foto()).status_code == 200
    assert _texto(c) == 200
    assert enviar(c, foto()).status_code == 429


@pytest.mark.parametrize(
    ("env", "esperado"),
    [
        ({}, 30),
        ({"BUSCA_CONSULTAS_POR_MINUTO": ""}, 30),
        ({"BUSCA_CONSULTAS_POR_MINUTO": "500"}, 500),
    ],
)
def test_ambiente_valido(env: dict[str, str], esperado: int) -> None:
    assert consultas_por_minuto_do_ambiente(env) == esperado


@pytest.mark.parametrize("valor", ["0", "-5", "1.5", "muitas"])
def test_ambiente_invalido_falha_com_erro_claro(valor: str) -> None:
    with pytest.raises(ValueError, match="BUSCA_CONSULTAS_POR_MINUTO"):
        consultas_por_minuto_do_ambiente({"BUSCA_CONSULTAS_POR_MINUTO": valor})


# --- cabeçalho de teste de carga (#580) ----------------------------------------------


def _cliente_de_teste(chave: bool, maximo: int = 30) -> tuple[Any, EventosEmMemoria]:
    eventos = EventosEmMemoria()
    c, _ = cliente(
        ["consulta"],
        *VESTIDO,
        *[pedido(texto_livre="vestido")] * 4,
        maximo_por_minuto=maximo,
        eventos=eventos,
        aceita_teste_de_carga=chave,
    )
    return c, eventos


def _buscas(eventos: EventosEmMemoria) -> int:
    return [e.tipo for e in eventos.publicados].count("busca")


def _pedir(c: Any, rota: str, cabecalho: str | None) -> Any:
    h = dict(AUTORIZACAO)
    if cabecalho is not None:
        h[CABECALHO_DE_TESTE] = cabecalho
    if rota == "texto":
        return c.get("/v1/busca", params={"q": "vestido"}, headers=h)
    return c.post(
        "/v1/busca/imagem",
        files={"arquivo": ("f.jpg", foto(), "image/jpeg")},
        headers=h,
    )


@pytest.mark.parametrize("rota", ["texto", "imagem"])
@pytest.mark.parametrize(
    ("chave", "cabecalho", "publica"),
    [
        (True, "1", False),
        (True, "2", True),
        (True, "true", True),
        (False, "1", True),
        (True, None, True),
        (False, None, True),
    ],
)
def test_so_a_chave_ligada_com_o_cabecalho_1_suprime_o_evento(
    rota: str, chave: bool, cabecalho: str | None, publica: bool
) -> None:
    c, eventos = _cliente_de_teste(chave)
    r = _pedir(c, rota, cabecalho)
    assert r.status_code == 200
    assert _buscas(eventos) == (1 if publica else 0)


@pytest.mark.parametrize("rota", ["texto", "imagem"])
@pytest.mark.parametrize("cabecalho", ["1" * 17, "1\x01", "1\x7f"])
def test_cabecalho_longo_ou_com_controle_volta_422(rota: str, cabecalho: str) -> None:
    c, eventos = _cliente_de_teste(True)
    assert _pedir(c, rota, cabecalho).status_code == 422
    assert _buscas(eventos) == 0


@pytest.mark.parametrize("rota", ["texto", "imagem"])
@pytest.mark.parametrize("cabecalho", [None, "1"])
def test_o_cabecalho_nao_isenta_do_limite(rota: str, cabecalho: str | None) -> None:
    c, _ = _cliente_de_teste(True, maximo=1)
    assert _pedir(c, rota, cabecalho).status_code == 200
    assert _pedir(c, rota, cabecalho).status_code == 429


@pytest.mark.parametrize("rota", ["texto", "imagem"])
def test_pagina_seguinte_nao_publica_evento(rota: str) -> None:
    eventos = EventosEmMemoria()
    c, m = cliente(
        ["consulta"],
        *VESTIDO,
        pedido(texto_livre="vestido"),
        eventos=eventos,
    )
    m.com(job("j2"), objeto("b", "j2", 0, 1_000))

    def pedir(**p: str) -> Any:
        if rota == "texto":
            return c.get("/v1/busca", params={"q": "vestido", **p}, headers=AUTORIZACAO)
        return c.post(
            "/v1/busca/imagem",
            files={"arquivo": ("f.jpg", foto(), "image/jpeg")},
            params=p,
            headers=AUTORIZACAO,
        )

    r1 = pedir(limite="1")
    assert _buscas(eventos) == 1
    r2 = pedir(limite="1", cursor=r1.headers["X-Proximo-Cursor"])
    assert r2.status_code == 200
    assert _buscas(eventos) == 1


@pytest.mark.parametrize(
    ("env", "esperado"),
    [
        ({}, False),
        ({"BUSCA_ACEITA_TESTE_DE_CARGA": ""}, False),
        ({"BUSCA_ACEITA_TESTE_DE_CARGA": "false"}, False),
        ({"BUSCA_ACEITA_TESTE_DE_CARGA": "true"}, True),
    ],
)
def test_chave_do_ambiente(env: dict[str, str], esperado: bool) -> None:
    assert aceita_teste_de_carga_do_ambiente(env) is esperado


# --- a página seguinte gasta o contador de páginas, não o de consultas (#803) -------


def _com_videos(
    consultas: int = 1, maximo_por_minuto: int = 30, paginas_por_minuto: int = 120
) -> TestClient:
    """3 vídeos com um vestido cada, para paginar de 1 em 1."""
    c, m = cliente(
        ["consulta"],
        *[pedido(texto_livre="vestido")] * consultas,
        maximo_por_minuto=maximo_por_minuto,
        paginas_por_minuto=paginas_por_minuto,
    )
    for i in (2, 3):
        m.com(job(f"j{i}"), objeto(f"o{i}", f"j{i}", 0, 1_000))
    return c


def _pagina(c: TestClient, cursor: str | None = None) -> Any:
    params: dict[str, Any] = {"q": "vestido", "limite": 1}
    if cursor is not None:
        params["cursor"] = cursor
    return c.get("/v1/busca", params=params, headers=AUTORIZACAO)


def test_3_paginas_de_uma_busca_gastam_1_consulta_e_2_paginas() -> None:
    c = _com_videos(maximo_por_minuto=1, paginas_por_minuto=2)
    p1 = _pagina(c)
    p2 = _pagina(c, p1.headers["X-Proximo-Cursor"])
    p3 = _pagina(c, p2.headers["X-Proximo-Cursor"])
    assert [p.status_code for p in (p1, p2, p3)] == [200, 200, 200]
    assert _pagina(c, p1.headers["X-Proximo-Cursor"]).status_code == 429  # sem páginas
    assert _texto(c) == 429  # sem consultas


def test_os_dois_tetos_sao_independentes() -> None:
    c = _com_videos(consultas=3, maximo_por_minuto=3, paginas_por_minuto=2)
    cursor = _pagina(c).headers["X-Proximo-Cursor"]
    assert _pagina(c).status_code == 200
    assert _pagina(c).status_code == 200
    assert _pagina(c).status_code == 429  # a 4ª consulta nova
    assert _pagina(c, cursor).status_code == 200  # ainda há saldo de páginas


def test_a_pagina_n_passa_e_a_n_mais_1_volta_429() -> None:
    c = _com_videos(paginas_por_minuto=2)
    cursor = _pagina(c).headers["X-Proximo-Cursor"]
    assert [_pagina(c, cursor).status_code for _ in range(3)] == [200, 200, 429]


def test_cursor_recusado_gasta_uma_pagina_e_sem_saldo_da_429() -> None:
    c = _com_videos(paginas_por_minuto=1)
    cursor = _pagina(c).headers["X-Proximo-Cursor"]
    assert _pagina(c, "0" * 20 + ".1").status_code == 422
    assert _pagina(c, cursor).status_code == 429
    assert _pagina(c, "0" * 20 + ".1").status_code == 429


def test_foto_com_cursor_e_sem_saldo_de_paginas_nao_e_recodificada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, m = cliente(["consulta"], *VESTIDO, paginas_por_minuto=1)
    m.com(job("j2"), objeto("b", "j2", 0, 1_000))
    dados = foto()
    cursor = enviar(c, dados, limite="1").headers["X-Proximo-Cursor"]
    assert enviar(c, dados, limite="1", cursor=cursor).status_code == 200

    def proibida(*_: Any, **__: Any) -> Any:
        raise AssertionError("recodificou")

    monkeypatch.setattr("api.rota_da_busca.recodificar", proibida)
    assert enviar(c, dados, limite="1", cursor=cursor).status_code == 429


@pytest.mark.parametrize(
    ("env", "esperado"),
    [
        ({}, 120),
        ({"BUSCA_PAGINAS_POR_MINUTO": ""}, 120),
        ({"BUSCA_PAGINAS_POR_MINUTO": "7"}, 7),
    ],
)
def test_ambiente_das_paginas(env: dict[str, str], esperado: int) -> None:
    assert paginas_por_minuto_do_ambiente(env) == esperado


@pytest.mark.parametrize("valor", ["0", "-5", "1.5", "muitas"])
def test_ambiente_das_paginas_invalido_falha_com_erro_claro(valor: str) -> None:
    with pytest.raises(ValueError, match="BUSCA_PAGINAS_POR_MINUTO"):
        paginas_por_minuto_do_ambiente({"BUSCA_PAGINAS_POR_MINUTO": valor})


def test_do_ambiente_ate_a_rota_o_teto_de_paginas_menor_da_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUSCA_PAGINAS_POR_MINUTO", "2")
    c = _com_videos(paginas_por_minuto=paginas_por_minuto_do_ambiente(os.environ))
    cursor = _pagina(c).headers["X-Proximo-Cursor"]
    assert [_pagina(c, cursor).status_code for _ in range(3)] == [200, 200, 429]
