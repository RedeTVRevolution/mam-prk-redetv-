import itertools

import pytest

from api.indice_da_busca import IndiceEmMemoria
from api.medir_busca import medir, percentil, tabela


def test_percentil_por_posicao_mais_proxima() -> None:
    tempos = [float(n) for n in range(1, 101)]
    assert percentil(tempos, 50) == 50.0
    assert percentil(tempos, 95) == 95.0
    assert percentil([7.0], 95) == 7.0


def test_medicao_com_o_duble_confere_o_filtro_composto_e_conta_os_registros() -> None:
    relogio = itertools.count(0.0, 0.01)
    resultado = medir(
        IndiceEmMemoria(), dimensao=256, consultas=10, relogio=relogio.__next__
    )
    assert resultado.so_o_objeto_da_sabrina
    assert resultado.registros == 16  # 3 vídeos: planos, falas, textos e objetos
    assert len(resultado.tempos_s) == 10
    assert resultado.p50_s == pytest.approx(0.01)


def test_medicao_apaga_os_videos_de_exemplo_no_fim() -> None:
    indice = IndiceEmMemoria()
    medir(indice, dimensao=256, consultas=1, relogio=_zero)
    assert indice.total() == 0


def _zero() -> float:
    return 0.0


def test_tabela_mostra_dimensao_registros_e_percentis() -> None:
    resultado = medir(IndiceEmMemoria(), dimensao=128, consultas=5, relogio=_zero)
    texto = tabela([resultado])
    assert "dimensão" in texto
    assert "128" in texto
    assert "16" in texto
    assert "p50" in texto and "p95" in texto
