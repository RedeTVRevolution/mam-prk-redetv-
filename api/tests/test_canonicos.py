"""Enquadramento e ambiente canônicos (#545): o dicionário do acervo."""

from collections.abc import Callable

import pytest

from api.canonicos import (
    _AMBIENTES,
    _ENQUADRAMENTOS,
    ambiente_canonico,
    enquadramento_canonico,
)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Plano médio", "plano médio"),
        ("médio", "plano médio"),
        ("Médio", "plano médio"),
        ("Plano Médio", "plano médio"),
        ("Close", "primeiro plano"),
        ("close", "primeiro plano"),
        ("Close-up", "primeiro plano"),
        ("Primeiríssimo plano", "primeiríssimo plano"),
        ("super close", "primeiríssimo plano"),
        ("Plano aberto", "plano geral"),
        ("plano geral", "plano geral"),
        ("Plano de conjunto", "plano de conjunto"),
        ("plano americano", "plano americano"),
        ("Plano detalhe", "detalhe"),
        ("primeiro plano", "primeiro plano"),
        ("Média", "plano médio"),
        ("MEDIA", "plano médio"),
        ("câmera mediante gesto", "indefinido"),
        ("Plano aproximado", "primeiro plano"),
        ("APROXIMADO", "primeiro plano"),
        ("Amplo", "plano geral"),
        ("plano AMPLO", "plano geral"),
        ("Close com amplo desfoque de fundo", "primeiro plano"),
        ("Plano médio com amplo desfoque", "plano médio"),
        ("Corpo inteiro", "plano de conjunto"),
        ("CORPO INTEIRO", "plano de conjunto"),
        ("", "indefinido"),
        ("câmera subjetiva esquisita", "indefinido"),
        ("Plano panorâmico", "plano geral"),
        ("tomada panorâmica", "plano geral"),
        ("Detalhes das mãos", "detalhe"),
        ("planos médios", "plano médio"),
    ],
)
def test_enquadramento(texto: str, esperado: str) -> None:
    assert enquadramento_canonico(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("estúdio", "estúdio"),
        ("Estúdio", "estúdio"),
        ("estudio", "estúdio"),
        ("Estúdio de TV", "estúdio"),
        ("rua", "externa"),
        ("Externo", "externa"),
        ("área externo", "externa"),
        ("Lanchonete", "comércio"),
        ("Supermercado", "comércio"),
        ("SUPERMERCADO", "comércio"),
        ("Padaria", "comércio"),
        ("padaria do bairro", "comércio"),
        ("Aeroporto", "aeroporto"),
        ("estádio de futebol", "estádio"),
        ("sala de estar", "residência"),
        ("Estúdios da emissora", "estúdio"),
        ("bastidores do show", "bastidor"),
        ("casal na praça", "externa"),
        ("carrossel no parque", "natureza"),
        ("lugar nenhum conhecido", "outro"),
        ("", "outro"),
    ],
)
def test_ambiente(texto: str, esperado: str) -> None:
    assert ambiente_canonico(texto) == esperado


_TERMOS = [
    (termo, valor, f)
    for regras, f in (
        (_ENQUADRAMENTOS, enquadramento_canonico),
        (_AMBIENTES, ambiente_canonico),
    )
    for termos, valor in regras
    for termo in termos
]


@pytest.mark.parametrize(("termo", "valor", "f"), _TERMOS)
def test_termo_nao_casa_so_o_comeco_de_palavra_maior(
    termo: str, valor: str, f: Callable[[str], str]
) -> None:
    assert f(termo) == valor
    # "campo de futebolx" cai em "campo": o que não pode é seguir no valor do termo inteiro.
    assert f(termo + "x") != valor
