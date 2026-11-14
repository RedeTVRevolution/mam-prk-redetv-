import pytest

from api.ambiente import FaltaNoAmbiente
from api.precos_dos_modelos import Preco, precos_do_ambiente


def test_precos_do_ambiente() -> None:
    assert precos_do_ambiente("a=0.1:0.4, b=1:4") == {
        "a": Preco(0.1, 0.4),
        "b": Preco(1.0, 4.0),
    }
    with pytest.raises(FaltaNoAmbiente):
        precos_do_ambiente("a=caro")
