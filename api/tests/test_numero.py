import pytest

from api.numero import formas, mesma_palavra, singular


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
