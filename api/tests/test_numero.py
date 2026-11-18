import json
from pathlib import Path
from typing import Any

import pytest

from api.numero import com_as_formas, formas, mesma_palavra, singular
from api.texto import normalizar


@pytest.mark.parametrize(
    "plural, esperado",
    [
        ("microfones", "microfone"),
        ("cadeiras", "cadeira"),
        ("vestidos", "vestido"),
        ("vermelhos", "vermelho"),
        ("promoções", "promoção"),
        ("aviões", "avião"),
        ("mãos", "mão"),
        ("pães", "pão"),
        ("animais", "animal"),
        ("mulheres", "mulher"),
        ("luzes", "luz"),
        ("homens", "homem"),
        ("microfone", "microfone"),
        ("mas", "mas"),
    ],
)
def test_singular(plural: str, esperado: str) -> None:
    assert singular(plural) == esperado


def test_formas_traz_a_palavra_o_singular_e_o_plural() -> None:
    assert formas("microfones") == {"microfones", "microfone"}
    assert formas("microfone") == {"microfone", "microfones"}
    assert {"animal", "animais"} <= formas("animal")
    assert {"promocao", "promocoes"} <= formas("promoção")


def test_mesma_palavra_ignora_acento_maiuscula_e_numero() -> None:
    assert mesma_palavra("Promoções", "promocao")
    assert not mesma_palavra("microfone", "cadeira")


@pytest.mark.parametrize(
    "plural, esperado",
    [
        ("papéis", "papel"),
        ("papeis", "papel"),
        ("hotéis", "hotel"),
        ("anzóis", "anzol"),
        ("acoes", "acao"),
        ("mães", "mãe"),
        ("reis", "rei"),
        ("meses", "mês"),
        ("países", "país"),
        ("heróis", "herói"),
    ],
)
def test_singular_com_acento_sem_acento_e_irregular(plural: str, esperado: str) -> None:
    assert singular(plural) == esperado


@pytest.mark.parametrize("palavra", ["mais", "seis", "deus", "país", "ônibus", "lápis"])
def test_palavra_sem_plural_fica_como_esta(palavra: str) -> None:
    assert singular(palavra) == palavra


def test_mesma_palavra_sem_falso_positivo_e_sem_acento() -> None:
    assert mesma_palavra("papel", "papéis")
    assert mesma_palavra("acoes", "ação")
    assert mesma_palavra("mês", "meses")
    assert not mesma_palavra("mal", "mais")
    # Sem acento "pais" é de pai e de país: com acento ou não, a resposta é a mesma.
    assert mesma_palavra("pai", "país") == mesma_palavra("pai", "pais")


def test_com_as_formas_deixa_a_pontuacao_de_fora() -> None:
    assert (
        com_as_formas("microfones, cadeiras!")
        == "(microfones OR microfone) (cadeiras OR cadeira)"
    )


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("carro", "(carro OR carros)"),
        ("homem de terno", "(homem OR homens) (de OR des) (terno OR ternos)"),
        ("ÔNIBUS", "onibus"),
        ("Mães", "(maes OR mae)"),
        ("carro CARRO carro", "(carro OR carros)"),
        ("mães MAES", "(maes OR mae)"),
        ("promoção", "(promocao OR promocaes OR promocaos OR promocoes)"),
        ("OR or", "(or OR ores)"),
        (
            '"CARRO"-(vestido) OR gravata',
            "(carro OR carros) (vestido OR vestidos) (or OR ores) (gravata OR gravatas)",
        ),
        ("", ""),
    ],
)
def test_com_as_formas_normaliza_deduplica_e_agrupa(texto: str, esperado: str) -> None:
    assert com_as_formas(texto) == esperado


GABARITO = json.loads((Path(__file__).parent / "assinatura_do_nome.json").read_text())


@pytest.mark.parametrize("caso", GABARITO["formas"], ids=lambda c: c["palavra"])
def test_formas_do_gabarito(caso: dict[str, Any]) -> None:
    achadas = formas(caso["palavra"])
    assert {normalizar(p) for p in caso["contem"]} <= achadas
    assert not {normalizar(p) for p in caso["nao_contem"]} & achadas


@pytest.mark.parametrize(
    "plural, esperado",
    [
        ("torres", "torre"),
        ("padres", "padre"),
        ("livres", "livre"),
        ("lustres", "lustre"),
        ("árvores", "árvore"),
        ("arvores", "árvore"),
        ("flores", "flor"),
        ("bares", "bar"),
        ("mulheres", "mulher"),
    ],
)
def test_singular_de_res(plural: str, esperado: str) -> None:
    assert singular(plural) == esperado


PARES_DE_ACENTO = [
    "pão", "pães", "mão", "mãos", "cão", "cães", "irmão", "irmãos", "alemães",
    "mês", "meses", "gás", "gases", "país", "países", "árvore", "árvores", "mães",
    "promoções", "papéis", "ônibus", "Itaú",
]  # fmt: skip


@pytest.mark.parametrize("palavra", PARES_DE_ACENTO)
def test_com_as_formas_igual_com_e_sem_acento(palavra: str) -> None:
    sem = normalizar(palavra)
    assert (
        com_as_formas(palavra) == com_as_formas(sem) == com_as_formas(palavra.upper())
    )


@pytest.mark.parametrize("palavra", PARES_DE_ACENTO)
def test_mesma_palavra_igual_com_e_sem_acento(palavra: str) -> None:
    for outra in PARES_DE_ACENTO:
        assert mesma_palavra(palavra, outra) == mesma_palavra(
            normalizar(palavra), outra
        )


@pytest.mark.parametrize(
    "a, b",
    [
        ("paes", "pão"),
        ("pao", "pães"),
        ("caes", "cão"),
        ("mes", "meses"),
        ("gas", "gases"),
        ("pais", "países"),
    ],
)
def test_sem_acento_acha_o_outro_numero(a: str, b: str) -> None:
    assert mesma_palavra(a, b)
    assert normalizar(b) in com_as_formas(a)


def test_maes_nao_vira_mao() -> None:
    assert not mesma_palavra("maes", "mão")
    assert "mao" not in com_as_formas("maes").split(" OR ")


def test_mao_nao_vira_maes() -> None:
    assert "maes" not in com_as_formas("mao")
    assert "maes" not in com_as_formas("mão")
