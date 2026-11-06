import itertools

import pytest

from api.indice_da_busca import Consulta, IndiceEmMemoria, Registro
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
    assert resultado.cor_filtra
    assert resultado.registros == 16  # 3 vídeos: planos, falas, textos e objetos
    assert len(resultado.tempos_s) == 10
    assert resultado.p50_s == pytest.approx(0.01)


def test_cada_repeticao_medida_leva_um_significado_novo() -> None:
    """Sem índice ANN o embedding da consulta é guardado por texto: repetir o mesmo texto
    mediria só a primeira chamada ao `predict`."""
    indice = IndiceEmMemoria()
    vistos: list[str | None] = []
    buscar = indice.buscar

    def registrar(consulta: Consulta) -> list[Registro]:
        vistos.append(consulta.significado)
        return buscar(consulta)

    indice.buscar = registrar  # type: ignore[method-assign]
    medir(indice, dimensao=256, consultas=5, relogio=_zero)
    medidas = vistos[2:]  # as duas primeiras são as conferências
    assert len(medidas) == 5 and len(set(medidas)) == 5


def test_medicao_apaga_os_videos_de_exemplo_no_fim() -> None:
    indice = IndiceEmMemoria()
    medir(indice, dimensao=256, consultas=1, relogio=_zero)
    assert indice.total() == 0


def test_medir_sem_consultas_e_erro() -> None:
    with pytest.raises(ValueError):
        medir(IndiceEmMemoria(), dimensao=256, consultas=0, relogio=_zero)


def _zero() -> float:
    return 0.0


def test_tabela_mostra_dimensao_registros_e_percentis() -> None:
    resultado = medir(IndiceEmMemoria(), dimensao=128, consultas=5, relogio=_zero)
    texto = tabela([resultado])
    assert "dimensão" in texto
    assert "128" in texto
    assert "16" in texto
    assert "p50" in texto and "p95" in texto
    assert "cor filtra" in texto
