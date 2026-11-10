"""Enquadramento e ambiente canônicos (#545): o dicionário do acervo."""

import pytest

from api.canonicos import ambiente_canonico, enquadramento_canonico


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
        ("lugar nenhum conhecido", "outro"),
        ("", "outro"),
    ],
)
def test_ambiente(texto: str, esperado: str) -> None:
    assert ambiente_canonico(texto) == esperado
