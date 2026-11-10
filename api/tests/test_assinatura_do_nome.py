import json
import random
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from api.assinatura_do_nome import assinatura

CASOS = json.loads((Path(__file__).parent / "assinatura_do_nome.json").read_text())[
    "casos"
]


@pytest.mark.parametrize("caso", CASOS, ids=lambda c: c["entrada"] or "vazio")
def test_a_tabela_de_exemplos(caso: dict[str, Any]) -> None:
    assert assinatura(caso["entrada"], caso["cores"]) == caso["chave"]


PALAVRAS = [
    ("camisa", "camisas"),
    ("microfone", "microfones"),
    ("violão", "violões"),
    ("flor", "flores"),
    ("animal", "animais"),
    ("guarda-chuva", "guarda-chuvas"),
    ("mesa", "mesas"),
]


@given(
    st.lists(st.sampled_from(PALAVRAS), min_size=1, max_size=4),
    st.lists(st.booleans(), min_size=4, max_size=4),
    st.randoms(use_true_random=False),
)
def test_ordem_e_plural_nao_mudam_a_chave(
    pares: list[tuple[str, str]], plurais: list[bool], azar: random.Random
) -> None:
    base = " ".join(s for s, _ in pares)
    outra = [p if plurais[i] else s for i, (s, p) in enumerate(pares)]
    azar.shuffle(outra)
    assert assinatura(base) == assinatura(" ".join(outra))


@given(
    st.text(max_size=40), st.lists(st.sampled_from(["vermelho", "azul"]), max_size=2)
)
def test_a_chave_da_chave_e_a_propria_chave(texto: str, cores: list[str]) -> None:
    chave = assinatura(texto, cores)
    assert assinatura(chave, cores) == chave
