"""`api/acento.py`: o acento de volta antes do significado e do Ranking (#731)."""

import time

import pytest

from api import acento
from api.acento import com_acento


@pytest.mark.parametrize("digitado", ["praça", "praca", "PRACA", "Praça"])
def test_a_palavra_comum_vem_com_o_acento_e_em_minuscula(digitado: str) -> None:
    assert com_acento(f"{digitado} da Sé") == "praça da Sé"


def test_a_palavra_sem_grafia_com_acento_fica_como_foi_digitada() -> None:
    assert (
        com_acento("Praia, OCULOS escuros e Cozinha!")
        == "Praia, óculos escuros e Cozinha!"
    )


@pytest.mark.parametrize(
    "digitado, esperado",
    [("manha", "manhã"), ("publico", "público"), ("eleicao", "eleição")],
)
def test_a_grafia_com_acento_muito_mais_comum_vence(
    digitado: str, esperado: str
) -> None:
    assert com_acento(digitado) == esperado


@pytest.mark.parametrize(
    "palavra",
    [
        "pais",
        "país",
        "coco",
        "cocô",
        "e",
        "esta",
        "está",
        "maca",
        "metro",
        "marco",
        "maio",
        "sabia",
        "secretaria",
        "2a",
        "1o",
    ],
)
def test_a_palavra_ambigua_nao_muda(palavra: str) -> None:
    assert com_acento(palavra) == palavra


def test_a_palavra_intocada_nao_muda() -> None:
    assert com_acento("Rita Leao e o leao", intocadas={"leao"}) == "Rita Leao e o leao"
    assert com_acento("o leao") == "o leão"


def test_sem_as_frequencias_a_busca_segue_com_o_texto_digitado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def falha(*_: object) -> dict[str, float]:
        raise OSError("sem os dados da wordfreq")

    monkeypatch.setattr(acento, "get_frequency_dict", falha)
    acento._montar.cache_clear()
    try:
        assert com_acento("praca") == "praca"
    finally:
        acento._montar.cache_clear()


def test_a_restauracao_leva_menos_de_1_ms_por_consulta() -> None:
    com_acento("aquece")
    inicio = time.perf_counter()
    for _ in range(1_000):
        com_acento("homem de oculos escuros na praca em frente a arvore do onibus")
    assert (time.perf_counter() - inicio) / 1_000 < 0.001
