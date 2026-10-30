import dataclasses
import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from api.janelas import CONTEXTO_MS, DURACAO_DA_JANELA_MS, Janela, planejar_janelas

HORA_MS = 3_600_000


def test_constantes_do_plano() -> None:
    assert DURACAO_DA_JANELA_MS == 300_000
    assert CONTEXTO_MS == 10_000


def test_tres_horas_dao_36_janelas() -> None:
    janelas = planejar_janelas(3 * HORA_MS)
    assert len(janelas) == 36
    assert janelas[-1].fim_ms == 3 * HORA_MS


def test_primeira_janela_de_varias_tem_contexto_limitado_no_comeco() -> None:
    primeira = planejar_janelas(900_000)[0]
    assert (primeira.inicio_contexto_ms, primeira.fim_contexto_ms) == (0, 310_000)


def test_duracao_zero_nao_tem_janela() -> None:
    assert planejar_janelas(0) == []


def test_duracao_negativa_e_erro() -> None:
    with pytest.raises(ValueError):
        planejar_janelas(-1)


def test_video_de_1_s_tem_uma_janela_com_contexto_limitado_nos_dois_lados() -> None:
    assert planejar_janelas(1_000) == [Janela(0, 0, 1_000, 0, 1_000)]


def test_video_de_299_s_tem_uma_janela() -> None:
    assert planejar_janelas(299_000) == [Janela(0, 0, 299_000, 0, 299_000)]


def test_video_de_exatamente_300_s_nao_gera_janela_vazia() -> None:
    assert planejar_janelas(300_000) == [Janela(0, 0, 300_000, 0, 300_000)]


def test_video_de_301_s_tem_ultima_janela_curta_com_contexto_na_borda() -> None:
    assert planejar_janelas(301_000) == [
        Janela(0, 0, 300_000, 0, 301_000),
        Janela(1, 300_000, 301_000, 290_000, 301_000),
    ]


def test_contexto_de_uma_janela_do_meio_tem_10_s_de_cada_lado() -> None:
    meio = planejar_janelas(900_000)[1]
    assert (meio.inicio_ms, meio.fim_ms) == (300_000, 600_000)
    assert (meio.inicio_contexto_ms, meio.fim_contexto_ms) == (290_000, 610_000)


def test_multiplo_exato_termina_na_duracao() -> None:
    janelas = planejar_janelas(900_000)
    assert [j.indice for j in janelas] == [0, 1, 2]
    assert janelas[-1].fim_ms == 900_000
    assert janelas[-1].fim_contexto_ms == 900_000


def test_nucleos_contiguos_somam_a_duracao() -> None:
    duracao = 3 * HORA_MS - 12_345
    janelas = planejar_janelas(duracao)
    assert janelas[0].inicio_ms == 0
    assert janelas[-1].fim_ms == duracao
    for anterior, seguinte in itertools.pairwise(janelas):
        assert anterior.fim_ms == seguinte.inicio_ms
    assert sum(j.fim_ms - j.inicio_ms for j in janelas) == duracao
    assert all(j.fim_ms > j.inicio_ms for j in janelas)


@given(st.integers(min_value=1, max_value=12 * HORA_MS))
def test_janelas_cobrem_qualquer_duracao_sem_buraco(duracao: int) -> None:
    janelas = planejar_janelas(duracao)
    assert janelas[0].inicio_ms == 0
    assert janelas[-1].fim_ms == duracao
    assert [j.indice for j in janelas] == list(range(len(janelas)))
    for anterior, seguinte in itertools.pairwise(janelas):
        assert anterior.fim_ms == seguinte.inicio_ms
    for j in janelas:
        assert 0 < j.fim_ms - j.inicio_ms <= DURACAO_DA_JANELA_MS
        assert j.inicio_contexto_ms == max(j.inicio_ms - CONTEXTO_MS, 0)
        assert j.fim_contexto_ms == min(j.fim_ms + CONTEXTO_MS, duracao)


def test_janela_e_imutavel() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        planejar_janelas(1_000)[0].indice = 1  # type: ignore[misc]
