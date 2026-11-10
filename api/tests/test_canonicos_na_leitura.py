"""O ambiente e o enquadramento canônicos na leitura da decupagem (#545)."""

import json
from typing import Any

from api.correcoes import versao_do_modelo
from api.tests.test_planos_e_falas import PLF, _descricao, _mundo, _plano


def _modelo(*planos: dict[str, Any]) -> dict[str, Any]:
    return {**PLF, "planos": list(planos)}


def _corrigir_ambiente(modelo: dict[str, Any], ambiente: str) -> dict[str, Any]:
    mundo = _mundo(modelo)
    mundo.corrigir(
        tipo="plano.descricao",
        item_id="pla01",
        valor=_descricao(ambiente=ambiente),
        versao=versao_do_modelo(json.dumps(modelo).encode()),
    )
    plano: dict[str, Any] = mundo.decupagem()["planos"][0]
    return plano


def test_decupagem_antiga_ganha_o_canonico_pelo_dicionario_e_o_texto_fica() -> None:
    modelo = _modelo(
        _plano("pla01", 0, 10000, ambiente="Estúdio de TV", enquadramento="Close-up"),
        _plano("pla02", 10000, 20000, ambiente="lugar esquisito"),
    )

    [p1, p2] = _mundo(modelo).decupagem()["planos"]

    assert (p1["ambiente"], p1["ambiente_canonico"]) == ("Estúdio de TV", "estúdio")
    assert (p1["enquadramento"], p1["enquadramento_canonico"]) == (
        "Close-up",
        "primeiro plano",
    )
    assert (p2["ambiente_canonico"], p2["enquadramento_canonico"]) == (
        "outro",
        "indefinido",
    )


def test_o_canonico_do_modelo_vale_quando_nao_ha_correcao() -> None:
    modelo = _modelo(
        _plano(
            "pla01",
            0,
            10000,
            ambiente="no set",
            ambiente_canonico="estúdio",
            enquadramento_canonico="plano geral",
        )
    )

    [p] = _mundo(modelo).decupagem()["planos"]

    assert (p["ambiente_canonico"], p["enquadramento_canonico"]) == (
        "estúdio",
        "plano geral",
    )


def test_correcao_antiga_de_ambiente_vale_e_o_canonico_a_segue() -> None:
    modelo = _modelo(
        _plano("pla01", 0, 10000, ambiente="estúdio", ambiente_canonico="estúdio")
    )

    p = _corrigir_ambiente(modelo, "Rua")

    assert (p["ambiente"], p["ambiente_canonico"]) == ("Rua", "externa")


def test_correcao_com_valor_fora_da_lista_vira_outro_sem_perder_o_texto() -> None:
    modelo = _modelo(
        _plano("pla01", 0, 10000, ambiente="estúdio", ambiente_canonico="estúdio")
    )

    p = _corrigir_ambiente(modelo, "submarino")

    assert (p["ambiente"], p["ambiente_canonico"]) == ("submarino", "outro")
