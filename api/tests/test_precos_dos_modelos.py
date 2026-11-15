import pytest

from api.ambiente import FaltaNoAmbiente
from api.precos_dos_modelos import Preco, lista_de_pares, precos_do_ambiente


def test_precos_do_ambiente() -> None:
    assert precos_do_ambiente("a=0.1:0.4, b=1:4") == {
        "a": Preco(0.1, 0.4),
        "b": Preco(1.0, 4.0),
    }
    with pytest.raises(FaltaNoAmbiente):
        precos_do_ambiente("a=caro")


def test_a_mensagem_do_preco_invalido_cita_a_variavel_e_o_item() -> None:
    with pytest.raises(FaltaNoAmbiente) as e:
        precos_do_ambiente("a=0.1:0.4, b=1:caro")

    assert str(e.value) == "preço inválido em PRECOS_DOS_MODELOS: 'b=1:caro'"


def test_a_lista_de_pares_le_inteiros_e_aceita_vazio() -> None:
    assert lista_de_pares("j1=10:2, j2=3:4,", int, "x") == {"j1": (10, 2), "j2": (3, 4)}
    assert lista_de_pares("", int, "x") == {}


def test_a_lista_de_pares_recusa_o_item_sem_dois_pontos_ou_do_tipo_errado() -> None:
    for item in ("j1=dez", "j1=10", "j1=1.5:2"):
        with pytest.raises(FaltaNoAmbiente) as e:
            lista_de_pares(f"j0=1:2, {item}", int, "tokens inválidos em TOKENS_DO_JOB")

        assert str(e.value) == f"tokens inválidos em TOKENS_DO_JOB: {item!r}"
