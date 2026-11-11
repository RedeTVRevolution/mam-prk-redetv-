"""Nomes do catálogo achados por dicionário (#568, item 4): igual ao regex de antes, sem
percorrer o catálogo a cada busca."""

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from api import entendimento_da_consulta
from api.catalogo import CatalogoEmMemoria, PessoaDoCatalogo
from api.comparador import normalizar
from api.entendimento_da_consulta import MAXIMO_DE_PESSOAS, entender, sanear
from api.tests.test_busca import Mundo


def _antigo(pessoas: list[PessoaDoCatalogo], consulta: str) -> tuple[str, ...]:
    """O `entender` de antes do #568, só a parte dos nomes (regex por pessoa)."""
    chave = normalizar(sanear(consulta))
    achadas = (
        sorted(
            (achado.start(), p.id)
            for p in pessoas
            if (nome := normalizar(p.nome))
            and (achado := re.search(r"(?<!\w)" + re.escape(nome) + r"(?!\w)", chave))
        )
        if chave
        else []
    )
    return tuple(dict.fromkeys(i for _, i in achadas))[:MAXIMO_DE_PESSOAS]


def _catalogo(*nomes: str) -> CatalogoEmMemoria:
    c = CatalogoEmMemoria()
    for n in nomes:
        c.acrescentar(n, "apresentador", [])
    return c


def _confere(c: CatalogoEmMemoria, consulta: str) -> tuple[str, ...]:
    esperado = _antigo(c.todas(), consulta)
    assert entender(consulta, catalogo=c).pessoas == esperado
    return esperado


@pytest.mark.parametrize(
    ("nomes", "consulta", "quantos"),
    [
        (["Ana Lima"], "foto da Ana Lima, no palco", 1),  # pontuação colada
        (["Ana Lima"], "(Ana Lima)", 1),
        (["Ana Lima"], "Ana Lima: entrevista", 1),
        (["Ana Lima"], "Ana-Lima", 0),  # hífen não é o espaço do nome
        (["Ana Lima"], "Ana_Lima", 0),  # sublinhado é \w
        (["Ana Lima"], "Ana Lima2", 0),  # dígito é \w
        (["Ana Lima"], "xAna Lima", 0),
        (["Ana"], "Ana Lima", 1),  # nome dentro de outro nome
        (["Ana", "Ana Lima"], "com Ana Lima", 2),
        (["Lima", "Ana Lima", "Ana"], "Ana Lima", 3),
        (["Ana Lima", "Ana Lima"], "Ana Lima", 2),  # dois cadastros, mesmo nome
        (["ANA LÍMA"], "ana lima", 1),  # acento e maiúscula
        (["Ana Lima"], "ÁNA LIMÁ!", 1),
        (["Ça Va"], "Ça va?", 1),
        (["Zé"], "o Zé,", 1),
        (["Zé"], "Zéca", 0),  # \w Unicode: letra acentuada é palavra
        (["Maria João"], "MARIA   JOÃO", 1),  # espaços colapsados
        (["M.I.A."], "ouvi M.I.A. ontem", 1),  # nome que termina em pontuação
        (["M.I.A."], "ouvi M.I.A.x ontem", 0),
        (["M.I.A."], "ouvi aM.I.A. ontem", 0),
        (["(Abc)"], "x(Abc)", 0),
        (["日本"], "日本語", 0),  # CJK é \w
        (["日本"], "日本 語", 1),
        (["  "], "a  b", 0),  # nome vazio depois de normalizar
        ([""], "texto", 0),
    ],
)
def test_casos_de_caracterizacao(nomes: list[str], consulta: str, quantos: int) -> None:
    assert len(_confere(_catalogo(*nomes), consulta)) == quantos


def test_empate_de_posicao_desempata_por_id() -> None:
    c = _catalogo("Ana", "Ana Lima", "Ana Lima Souza")  # as três na posição 0
    ids = _confere(c, "Ana Lima Souza")
    assert ids == tuple(sorted(ids)) and len(ids) == 3


def test_ordem_e_a_da_primeira_ocorrencia_na_consulta() -> None:
    c = _catalogo("Ana", "Bia", "Caio")
    ids = {p.nome: p.id for p in c.todas()}
    assert _confere(c, "Caio e Bia e Ana e Caio") == (
        ids["Caio"],
        ids["Bia"],
        ids["Ana"],
    )


def test_teto_de_pessoas_vem_depois_da_deduplicacao() -> None:
    nomes = ["A1", "B2", "C3", "D4", "E5", "F6", "G7"]
    c = _catalogo(*nomes, "A1")  # A1 duplicado: dois ids na mesma posição
    assert len(_confere(c, " ".join(nomes))) == MAXIMO_DE_PESSOAS


def test_homonimos_alem_do_teto_ficam_os_de_menor_id() -> None:
    c = _catalogo(*["Ana"] * 7, "Bia")
    assert _confere(c, "Bia e Ana") == tuple(
        [next(p.id for p in c.todas() if p.nome == "Bia")]
        + sorted(p.id for p in c.todas() if p.nome == "Ana")[: MAXIMO_DE_PESSOAS - 1]
    )


@settings(max_examples=300, deadline=None)
@given(
    nomes=st.lists(st.text(alphabet="aAbé_.- 1", min_size=0, max_size=6), max_size=8),
    consulta=st.text(alphabet='aAbBéÉ_.-," 1ç', max_size=40),
)
def test_aleatorio_igual_ao_regex_antigo(nomes: list[str], consulta: str) -> None:
    _confere(_catalogo(*nomes), consulta)


def test_nao_percorre_o_catalogo_a_cada_busca(monkeypatch: pytest.MonkeyPatch) -> None:
    m = Mundo()
    for i in range(50):
        m.catalogo.acrescentar(f"Pessoa Numero {i}", "apresentador", [])
    busca = m.busca()
    vistos: list[str] = []

    def contando(texto: str) -> str:
        vistos.append(texto)
        return normalizar(texto)

    monkeypatch.setattr(entendimento_da_consulta, "normalizar", contando)
    busca.buscar("vestido vermelho")  # a primeira busca monta o índice da cópia
    antes = len(vistos)
    for q in ("Pessoa Numero 7 de azul", "tênis", "Sabrina Sato"):
        busca.buscar(q)
    # nas buscas seguintes nenhum nome do catálogo passa por `normalizar`
    assert not [v for v in vistos[antes:] if re.fullmatch(r"Pessoa Numero \d+", v)]
