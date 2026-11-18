"""#716: o protocolo de texto do `antes` e do `depois`, no valor gravado e no rótulo.

Os valores saem de aplicar a Correção (rota e histórico), não de cadeias à mão.
"""

from typing import Any

import pytest

from api.catalogo_de_correcoes import (
    ler_ocorrencia,
    ler_separacao,
    ler_tempos,
    ocorrencia,
    separacao,
    tempos,
)
from api.tests.test_correcoes import Mundo
from api.tests.test_separar_pessoa import CHAVE_1, CHAVE_2, _mundo, _separar


def _ocorrencia(lista: str, inicio: int, fim: int) -> dict[str, Any]:
    return {"lista": lista, "inicio_ms": inicio, "fim_ms": fim}


def _lados(mundo: Mundo, **campos: Any) -> tuple[tuple[str, str], tuple[str, str]]:
    """((antes, depois) gravados, (antes, depois) legíveis) da última Correção."""
    assert mundo.corrigir(**campos).status_code == 201
    item = mundo.historico().json()[0]
    return (item["antes"], item["depois"]), (
        item["antes_legivel"],
        item["depois_legivel"],
    )


APARICAO = '{"inicio_ms": 20000, "fim_ms": 22000, "evidencia": "rosto"}'
# O que a Correção grava é o JSON canônico (chaves em ordem).
APARICAO_GRAVADA = '{"evidencia": "rosto", "fim_ms": 22000, "inicio_ms": 20000}'


@pytest.mark.parametrize(
    ("campos", "gravado", "legivel"),
    [
        (
            {"tipo": "item.tempos", "item_id": "pau01", "valor": "0-18000"},
            ("0-20000", "0-18000"),
            ("00:00–00:20", "00:00–00:18"),
        ),
        (
            {
                "tipo": "item.tempos",
                "tipo_do_item": "pessoa",
                "item_id": "pes01",
                "valor": "1500-4500",
                "ocorrencia": _ocorrencia("na_imagem", 1000, 5000),
            },
            ("1000-5000", "1500-4500"),
            ("00:01–00:05", "00:01–00:04"),
        ),
        (
            {
                "tipo": "pessoa.nao_e",
                "item_id": "pes01",
                "valor": "Não identificado",
                "ocorrencia": _ocorrencia("na_imagem", 1000, 5000),
            },
            ("na_imagem 1000-5000", "Não identificado"),
            ("aparição 00:01–00:05", "Não identificado"),
        ),
        (
            {
                "tipo": "pessoa.aparicao_para_mencao",
                "item_id": "pes01",
                "valor": "citada_no_texto",
                "ocorrencia": _ocorrencia("na_imagem", 1000, 5000),
            },
            ("na_imagem 1000-5000", "citada_no_texto"),
            ("aparição 00:01–00:05", "citada_no_texto"),
        ),
        (
            {
                "tipo": "pessoa.mencao_para_aparicao",
                "item_id": "pes01",
                "valor": "rosto no plano aberto",
                "ocorrencia": _ocorrencia("citada_na_fala", 5005, 5009),
            },
            ("citada_na_fala 5005-5009", "rosto no plano aberto"),
            ("citada na fala 00:05–00:05", "rosto no plano aberto"),
        ),
        (
            {
                "tipo": "pessoa.acrescentar_aparicao",
                "item_id": "pes01",
                "valor": APARICAO,
            },
            ("", APARICAO_GRAVADA),
            ("", "00:20–00:22 (rosto)"),
        ),
    ],
)
def test_cada_tipo_grava_e_rotula_cada_lado(
    campos: dict[str, Any], gravado: tuple[str, str], legivel: tuple[str, str]
) -> None:
    assert _lados(Mundo(["editor"]), **campos) == (gravado, legivel)


def test_separar_grava_as_origens_no_antes_e_a_escolhida_no_depois() -> None:
    mundo = _mundo()
    assert _separar(mundo).status_code == 201

    item = mundo.historico().json()[0]

    assert item["antes"] == f'["{CHAVE_1}", "{CHAVE_2}"]'
    assert item["depois"] == CHAVE_2
    assert item["antes_legivel"] == (
        "nao identificado, blusa vermelha 00:10–00:20; "
        "nao identificado, blusa vermelha 00:40–00:50"
    )
    assert item["depois_legivel"] == "nao identificado, blusa vermelha 00:40–00:50"


def test_ida_e_volta_dos_formatos_de_protocolo() -> None:
    assert ler_tempos("1000-5000") == (1000, 5000)
    assert ler_ocorrencia("na_imagem 1000-5000") == ("na_imagem", 1000, 5000)
    assert ler_separacao("ana lima@1000-5000") == ("ana lima", 1000, 5000)


@pytest.mark.parametrize(
    "cru",
    [
        "Não identificado",
        "texto livre 1-2",
        '{"inicio_ms": 1, "fim_ms": 2}',
        "1-2-3",
        "1234567890123-2",  # mais de 12 dígitos
        "na_imagem 1-2 ",
        "outra_lista 1-2",
        "",
    ],
)
def test_o_que_nao_e_protocolo_continua_cru(cru: str) -> None:
    assert ler_tempos(cru) is None
    assert ler_ocorrencia(cru) is None
    assert ler_separacao(cru) is None
    assert tempos(cru) == ocorrencia(cru) == separacao(cru) == cru
