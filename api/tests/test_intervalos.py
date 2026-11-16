"""Um teste por regra de borda de `api/intervalos.py`, com os pares que as separam."""

from api.intervalos import (
    comprimento_da_sobreposicao,
    sobrepoe_com_folga,
    sobrepoe_de_verdade,
    sobrepoe_estrito,
    sobrepoe_inclusivo,
    sobrepoe_metade,
)


def test_estrito_nao_conta_encostar() -> None:
    assert sobrepoe_estrito(0, 10, 5, 15)
    assert not sobrepoe_estrito(0, 10, 10, 20)  # encosta
    assert sobrepoe_estrito(10, 10, 0, 20)  # ponto dentro: o estrito conta
    assert not sobrepoe_estrito(0, 5, 10, 15)


def test_inclusivo_conta_encostar() -> None:
    assert sobrepoe_inclusivo(0, 10, 10, 20)
    assert sobrepoe_inclusivo(10, 10, 0, 20)
    assert not sobrepoe_inclusivo(0, 5, 10, 15)


def test_com_folga_alarga_so_o_primeiro() -> None:
    assert not sobrepoe_com_folga(0, 10, 10, 20, 0)  # folga 0 = estrita
    assert not sobrepoe_com_folga(
        0, 10, 11, 20, 1
    )  # folga igual à distância: borda estrita
    assert sobrepoe_com_folga(0, 10, 11, 20, 2)
    assert sobrepoe_com_folga(10, 20, 0, 8, 3)


def test_comprimento_em_inteiro_e_em_segundos() -> None:
    assert comprimento_da_sobreposicao(0, 10, 4, 20) == 6
    assert comprimento_da_sobreposicao(0, 10, 15, 20) == -5  # distância
    assert comprimento_da_sobreposicao(0.0, 1.5, 1.0, 3.0) == 0.5


def test_de_verdade_aceita_instante_dentro() -> None:
    assert sobrepoe_de_verdade(0, 10, 5, 15)
    assert not sobrepoe_de_verdade(0, 10, 10, 20)  # encosta: o inclusivo diz sim
    assert sobrepoe_de_verdade(5, 5, 0, 10)  # instante dentro: o estrito diz sim também
    assert sobrepoe_de_verdade(0, 10, 10, 10)  # instante na borda: o estrito diz não
    assert not sobrepoe_de_verdade(0, 5, 10, 10)


def test_metade_do_menor() -> None:
    assert sobrepoe_metade(0, 10, 5, 7)  # menor (2) coberto inteiro
    assert sobrepoe_metade(0, 10, 5, 15)  # 5 de 10
    assert not sobrepoe_metade(0, 10, 6, 16)  # 4 de 10
    assert not sobrepoe_metade(0, 10, 10, 20)  # encosta
    assert sobrepoe_metade(5, 5, 0, 10)  # instante dentro
    assert not sobrepoe_metade(0, 5, 10, 15)  # distantes


def test_regras_dao_resultados_diferentes_no_mesmo_par() -> None:
    encosta = (0, 10, 10, 20)
    assert sobrepoe_inclusivo(*encosta) and not sobrepoe_estrito(*encosta)
    assert not sobrepoe_de_verdade(*encosta) and not sobrepoe_metade(*encosta)
    instante_na_borda = (0, 10, 10, 10)
    assert not sobrepoe_estrito(*instante_na_borda)
    assert sobrepoe_de_verdade(*instante_na_borda)
