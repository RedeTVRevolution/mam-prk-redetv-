"""O inventário de objetos na Decupagem (#244): esquema, categorias e destaque."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from api.decupagem import (
    CATEGORIAS_DE_OBJETO,
    CaixaDoQuadro,
    Decupagem,
    esquema_do_modelo,
)
from api.inventario import destaque_da_caixa
from api.tests.test_decupagem import decupagem_valida

CAIXA = {
    "quadro": "quadros/plano-1.jpg",
    "x": 0.1,
    "y": 0.2,
    "largura": 0.3,
    "altura": 0.4,
}


def item(**mudancas: Any) -> dict[str, Any]:
    return {
        "nome": "sofá",
        "categoria": "movel",
        "cor": "cinza",
        "marca": None,
        "caixas": [CAIXA],
        "destaque": 2,
        **mudancas,
    }


def com_inventario(*itens: dict[str, Any]) -> dict[str, Any]:
    base = decupagem_valida()
    base["planos"][0]["inventario"] = list(itens)
    base["inventario_gerado_por"] = {"motor": "florence", "modelo": "gemini-x"}
    return base


def test_decupagem_com_inventario_passa_e_guarda_os_campos() -> None:
    d = Decupagem.model_validate(com_inventario(item()))

    achado = d.planos[0].inventario[0]
    assert (achado.nome, achado.categoria, achado.cor, achado.destaque) == (
        "sofá",
        "movel",
        "cinza",
        2,
    )
    assert achado.caixas[0].quadro == "quadros/plano-1.jpg"
    assert d.inventario_gerado_por is not None
    assert d.inventario_gerado_por.motor == "florence"


def test_decupagem_sem_inventario_continua_valida() -> None:
    d = Decupagem.model_validate(decupagem_valida())

    assert all(p.inventario == [] for p in d.planos)
    assert d.inventario_gerado_por is None


@pytest.mark.parametrize(
    "ruim",
    [
        item(categoria="inexistente"),
        item(cor="vinho"),
        item(destaque=0),
        item(destaque=4),
        item(caixas=[]),
        item(caixas=[{**CAIXA, "x": 1.2}]),
        item(caixas=[{**CAIXA, "largura": -0.1}]),
    ],
)
def test_inventario_fora_do_esquema_e_recusado(ruim: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Decupagem.model_validate(com_inventario(ruim))


def test_categorias_de_objeto_ganham_as_de_objeto_de_cena() -> None:
    assert {
        "movel",
        "decoracao",
        "instrumento_musical",
        "utensilio",
        "documento",
        "planta",
        "bebida",
    } <= set(CATEGORIAS_DE_OBJETO)


def test_o_inventario_nao_entra_no_esquema_da_analise() -> None:
    esquema = json.dumps(esquema_do_modelo())

    assert "inventario" not in esquema
    assert not {"CaixaDoQuadro", "ObjetoDoInventario", "GeradorDoInventario"} & set(
        esquema_do_modelo()["$defs"]
    )


@pytest.mark.parametrize(
    ("caixa", "esperado"),
    [
        # grande e no centro
        ({"x": 0.25, "y": 0.25, "largura": 0.5, "altura": 0.5}, 3),
        # grande, mas num canto
        ({"x": 0.6, "y": 0.6, "largura": 0.4, "altura": 0.4}, 2),
        # pequena e no centro
        ({"x": 0.45, "y": 0.45, "largura": 0.2, "altura": 0.2}, 2),
        # pequena e num canto
        ({"x": 0.0, "y": 0.0, "largura": 0.1, "altura": 0.1}, 1),
        # minúscula, mesmo no centro
        ({"x": 0.49, "y": 0.49, "largura": 0.05, "altura": 0.05}, 1),
    ],
)
def test_destaque_vem_do_tamanho_e_da_posicao(
    caixa: dict[str, float], esperado: int
) -> None:
    assert destaque_da_caixa(CaixaDoQuadro(quadro="q.jpg", **caixa)) == esperado
