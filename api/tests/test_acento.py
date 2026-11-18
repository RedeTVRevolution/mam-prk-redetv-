"""`api/acento.py`: o acento de volta antes do significado e do Ranking (#731)."""

import time
from pathlib import Path

import pytest

from api import acento
from api.acento import com_acento


@pytest.mark.parametrize("digitado", ["praça", "praca", "PRACA", "Praça"])
def test_a_palavra_do_dicionario_vem_com_o_acento_e_a_caixa_dele(digitado: str) -> None:
    assert com_acento(f"{digitado} da Sé") == "praça da Sé"


def test_a_palavra_fora_do_dicionario_fica_como_foi_digitada() -> None:
    assert (
        com_acento("Praia, OCULOS escuros e Cozinha!")
        == "Praia, óculos escuros e Cozinha!"
    )


@pytest.mark.parametrize(
    "palavra", ["pais", "país", "coco", "cocô", "e", "esta", "está", "maca", "Itau"]
)
def test_a_palavra_ambigua_e_a_marca_nao_mudam(palavra: str) -> None:
    assert com_acento(palavra) == palavra


def test_a_palavra_intocada_nao_muda() -> None:
    assert com_acento("Rita Leao e o leao", intocadas={"leao"}) == "Rita Leao e o leao"
    assert com_acento("o leao") == "o leão"


def test_o_dicionario_e_pequeno_sem_repeticao_e_so_com_acento() -> None:
    linhas = acento.ARQUIVO.read_text("utf-8").splitlines()
    palavras = [p.strip() for p in linhas if p.strip() and not p.startswith("#")]
    assert len(palavras) <= 5_000
    # Nenhuma grafia sem acento com duas leituras (avó/avô) nem palavra já sem acento.
    assert len(acento.dicionario()) == len(palavras)
    assert all(chave != valor for chave, valor in acento.dicionario().items())


def test_sem_o_dicionario_a_busca_segue_com_o_texto_digitado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acento, "ARQUIVO", Path("/nao/existe/acentos.txt"))
    acento.dicionario.cache_clear()
    try:
        assert com_acento("praca") == "praca"
    finally:
        acento.dicionario.cache_clear()


def test_a_restauracao_leva_menos_de_1_ms_por_consulta() -> None:
    com_acento("aquece")
    inicio = time.perf_counter()
    for _ in range(1_000):
        com_acento("homem de oculos escuros na praca em frente a arvore do onibus")
    assert (time.perf_counter() - inicio) / 1_000 < 0.001
