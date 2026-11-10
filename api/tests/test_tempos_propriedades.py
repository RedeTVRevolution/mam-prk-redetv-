"""Invariantes da regra de tempos para qualquer plano e qualquer corte (#545)."""

from itertools import pairwise

from hypothesis import assume, given
from hypothesis import strategies as st

from api.tempos import aplicar_regra_de_tempos
from api.tests.test_tempos import DURACAO_MS, decupagem

_tempo = st.integers(min_value=0, max_value=DURACAO_MS)
_intervalo = st.tuples(_tempo, _tempo).filter(lambda t: t[0] < t[1])
_planos = st.lists(_intervalo, max_size=8)
_cortes = st.lists(st.integers(min_value=1, max_value=DURACAO_MS - 1), max_size=20)


@given(_planos, _cortes)
def test_os_planos_saem_em_ordem_sem_sobreposicao_e_dentro_do_video(
    planos: list[tuple[int, int]], cortes: list[int]
) -> None:
    # Sem cortes, os planos do modelo passam como vieram (e podem se sobrepor).
    assume(cortes)
    saida = aplicar_regra_de_tempos(decupagem(planos=planos), cortes).planos

    pares = [(p.inicio_ms, p.fim_ms) for p in saida]
    assert all(0 <= i < f <= DURACAO_MS for i, f in pares)
    assert all(a[1] <= b[0] for a, b in pairwise(pares))


@given(_planos, _cortes)
def test_aplicar_a_regra_duas_vezes_da_o_mesmo_que_uma(
    planos: list[tuple[int, int]], cortes: list[int]
) -> None:
    uma = aplicar_regra_de_tempos(decupagem(planos=planos), cortes)

    assert aplicar_regra_de_tempos(uma, cortes) == uma
