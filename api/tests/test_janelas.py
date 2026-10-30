import dataclasses
import itertools
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from api.janelas import (
    CONTEXTO_MS,
    DURACAO_DA_JANELA_MS,
    LIMITE_DE_TENTATIVAS,
    EstadoJanela,
    Janela,
    concluir,
    falhar,
    iniciar,
    planejar_janelas,
    situacao_do_job,
)

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


def pendente(indice: int = 0) -> EstadoJanela:
    return EstadoJanela(indice=indice, situacao="pendente", tentativas=0, erro=None)


def concluida(indice: int = 0) -> EstadoJanela:
    return concluir(iniciar(pendente(indice)))


def falhou(indice: int = 0, erro: str = "boom") -> EstadoJanela:
    estado = pendente(indice)
    for _ in range(LIMITE_DE_TENTATIVAS):
        estado = falhar(iniciar(estado), erro)
    return estado


def test_limite_padrao_de_tentativas_e_tres() -> None:
    assert LIMITE_DE_TENTATIVAS == 3


def test_caminho_feliz() -> None:
    em_andamento = iniciar(pendente(2))
    assert em_andamento == EstadoJanela(2, "em_andamento", 1, None)
    assert concluir(em_andamento) == EstadoJanela(2, "concluida", 1, None)


def test_transicoes_nao_alteram_o_estado_original() -> None:
    original = pendente()
    iniciar(original)
    assert original == pendente()


@pytest.mark.parametrize("estado", [concluida(), falhou()])
def test_janela_terminal_nunca_e_refeita(estado: EstadoJanela) -> None:
    assert iniciar(estado) == estado
    assert concluir(estado) == estado
    assert falhar(estado, "outro erro") == estado


def test_falha_antes_do_limite_volta_a_pendente_mantendo_tentativas() -> None:
    estado = falhar(iniciar(pendente()), "timeout")
    assert estado == EstadoJanela(0, "pendente", 1, "timeout")


def test_falha_que_esgota_o_limite_vai_a_falhou_com_o_erro() -> None:
    estado = pendente()
    for _ in range(LIMITE_DE_TENTATIVAS - 1):
        estado = falhar(iniciar(estado), "x")
        assert estado.situacao == "pendente"
    estado = falhar(iniciar(estado), "último erro")
    assert estado == EstadoJanela(0, "falhou", LIMITE_DE_TENTATIVAS, "último erro")


def test_limite_e_parametro() -> None:
    estado = falhar(iniciar(pendente()), "x", limite=1)
    assert estado.situacao == "falhou"


def test_reiniciar_janela_em_andamento_conta_tentativa() -> None:
    estado = iniciar(iniciar(pendente()))
    assert estado == EstadoJanela(0, "em_andamento", 2, None)


def test_reinicio_alem_do_limite_vai_a_falhou() -> None:
    estado = pendente()
    for _ in range(LIMITE_DE_TENTATIVAS):
        estado = iniciar(estado)
    assert estado.situacao == "em_andamento"
    estado = iniciar(estado)
    assert estado.situacao == "falhou"
    assert estado.tentativas == LIMITE_DE_TENTATIVAS
    assert estado.erro


def test_concluir_apos_falha_limpa_o_erro() -> None:
    estado = concluir(iniciar(falhar(iniciar(pendente()), "timeout")))
    assert estado == EstadoJanela(0, "concluida", 2, None)


@pytest.mark.parametrize("transicao", [concluir, lambda e: falhar(e, "x")])
def test_concluir_ou_falhar_sem_iniciar_e_erro(
    transicao: Callable[[EstadoJanela], EstadoJanela],
) -> None:
    with pytest.raises(ValueError, match="não foi iniciada"):
        transicao(pendente())


def test_iniciar_janela_pendente_com_limite_esgotado_vai_a_falhou() -> None:
    estado = EstadoJanela(0, "pendente", LIMITE_DE_TENTATIVAS, "x")
    assert iniciar(estado).situacao == "falhou"


def test_progresso_parcial() -> None:
    situacao = situacao_do_job([concluida(0), iniciar(pendente(1)), pendente(2)])
    assert (situacao.prontas, situacao.total) == (1, 3)
    assert situacao.falha is None
    assert not situacao.pode_consolidar


def test_job_falho_aponta_a_primeira_janela_falha() -> None:
    estados = [concluida(0), falhou(3, "erro 3"), pendente(2), falhou(1, "erro 1")]
    situacao = situacao_do_job(estados)
    assert situacao.falha is not None
    assert (situacao.falha.indice, situacao.falha.erro) == (1, "erro 1")
    assert not situacao.pode_consolidar


def test_job_com_tudo_concluido_pode_consolidar() -> None:
    situacao = situacao_do_job([concluida(0), concluida(1)])
    assert (situacao.prontas, situacao.total) == (2, 2)
    assert situacao.falha is None
    assert situacao.pode_consolidar


def test_job_sem_janelas_nao_consolida() -> None:
    assert not situacao_do_job([]).pode_consolidar
