"""O limite de buscas por minuto vem da configuração (#577); o padrão continua 30."""

from typing import Any

import pytest

from api.eventos_de_uso import EventosEmMemoria
from api.rota_da_busca import consultas_por_minuto_do_ambiente
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
