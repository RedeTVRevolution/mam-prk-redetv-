"""O limite de buscas por minuto vem da configuração (#577); o padrão continua 30."""

from typing import Any

import pytest

from api.rota_da_busca import consultas_por_minuto_do_ambiente
from api.tests.test_busca import AUTORIZACAO, cliente, pedido
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
