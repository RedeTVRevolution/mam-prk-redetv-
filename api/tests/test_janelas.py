import dataclasses
import itertools

import pytest

from api.janelas import CONTEXTO_MS, DURACAO_DA_JANELA_MS, Janela, planejar_janelas

HORA_MS = 3_600_000


def test_constantes_do_plano() -> None:
    assert DURACAO_DA_JANELA_MS == 300_000
    assert CONTEXTO_MS == 10_000


def test_tres_horas_dao_36_janelas() -> None:
    assert len(planejar_janelas(3 * HORA_MS)) == 36


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


def test_janela_e_imutavel() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        planejar_janelas(1_000)[0].indice = 1  # type: ignore[misc]
