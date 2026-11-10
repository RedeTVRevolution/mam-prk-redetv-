"""A medição dos detectores de corte contra cortes marcados à mão (#545)."""

from api.comparar_detectores import Medida, medir


def test_precisao_e_cobertura_com_tolerancia() -> None:
    marcados = [1_000, 5_000, 9_000]
    detectados = [1_100, 2_000, 5_000, 5_050]  # 2 000 sobra; 5 050 repete o de 5 000; 9 000 falta

    m = medir(detectados, marcados, tolerancia_ms=200)

    assert m == Medida(acertos=2, detectados=4, marcados=3, precisao=0.5, cobertura=2 / 3)


def test_sem_detectar_nada_a_precisao_e_vazia_e_a_cobertura_zero() -> None:
    m = medir([], [1_000], tolerancia_ms=200)

    assert (m.precisao, m.cobertura) == (None, 0.0)


def test_cada_corte_marcado_so_vale_uma_vez() -> None:
    m = medir([1_000, 1_100], [1_050], tolerancia_ms=200)

    assert (m.acertos, m.precisao, m.cobertura) == (1, 0.5, 1.0)
