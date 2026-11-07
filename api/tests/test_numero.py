import pytest

from api.numero import com_as_formas, formas, mesma_palavra, singular


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
    assert {"promoção", "promoções"} <= formas("promoção")


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
    assert not mesma_palavra("pai", "país")


def test_com_as_formas_deixa_a_pontuacao_de_fora() -> None:
    assert (
        com_as_formas("microfones, cadeiras!")
        == "microfones microfone cadeiras cadeira"
    )
