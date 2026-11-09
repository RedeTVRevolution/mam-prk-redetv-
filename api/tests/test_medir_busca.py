import itertools
from dataclasses import replace

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
    assert resultado.so_o_plano_da_sabrina
    assert resultado.pessoa_filtra
    assert resultado.registros == 12  # Só os dois planos de cada vídeo
    assert len(resultado.tempos_s) == 10
    assert resultado.p50_s == pytest.approx(0.01)


@pytest.mark.parametrize(
    "ignorados",
    [
        {"programa": None},
        {"exibido_desde": None},
        {"exibido_ate": None},
        {"programa": None, "exibido_desde": None, "exibido_ate": None},
    ],
    ids=["programa", "desde", "ate", "programa-e-datas"],
)
def test_medicao_reprova_adaptador_que_ignora_programa_ou_datas(
    ignorados: dict[str, None],
) -> None:
    class IgnoraFiltros(IndiceEmMemoria):
        def buscar(self, consulta: Consulta) -> list[Registro]:
            return super().buscar(
                replace(consulta, filtros=replace(consulta.filtros, **ignorados))
            )

    resultado = medir(IgnoraFiltros(), dimensao=256, consultas=1, relogio=_zero)
    assert not resultado.so_o_plano_da_sabrina
    assert resultado.pessoa_filtra


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
    assert "12" in texto
    assert "p50" in texto and "p95" in texto
    assert "pessoa filtra" in texto


def test_medicao_so_grava_planos() -> None:
    class SoPlanos(IndiceEmMemoria):
        def gravar(self, job_id: str, registros: list[Registro]) -> None:
            assert registros and all(r.tipo == "plano" for r in registros)
            super().gravar(job_id, registros)

    medir(SoPlanos(), dimensao=256, consultas=1, relogio=_zero)


def test_medida_temporaria_nao_escreve_nem_apaga_na_colecao_de_texto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import Any

    from api.exemplos_da_busca import EXEMPLOS
    from api.medir_busca import main
    from api.tests.test_agent_retrieval import CONFIG, _ColecaoEmMemoria, _lido

    memoria = _ColecaoEmMemoria()
    salvo = f"{CONFIG.local}/collections/col-texto/dataObjects/m-ex-sabrina-fala"
    memoria.objetos[salvo] = {
        "id": "ex-sabrina:fala",
        "tipo": "fala",
        "job_id": "ex-sabrina",
    }
    alvo = next(r for r in EXEMPLOS[0].registros() if r.tipo == "plano")
    colecoes_criadas: list[str] = []

    def transporte(metodo: str, caminho: str, corpo: Any) -> dict[str, Any]:
        if "/col-texto/" in caminho:
            assert caminho.endswith(":query"), "a medição escreveu na coleção de texto"
        if "collectionId=" in caminho:
            colecoes_criadas.append(caminho)
            return {}
        if metodo == "DELETE" or "/indexes?" in caminho:
            return {}
        if caminho.endswith(":batchSearch"):
            pedido = corpo["searches"][0]["textSearch"]
            ausente = {"pessoas": {"$in": ["cat-ausente"]}} in pedido["filter"]["$and"]
            return {
                "results": [
                    {
                        "results": []
                        if ausente
                        else [{"dataObject": {"data": _lido(alvo)}}]
                    }
                ]
            }
        if caminho.endswith(":query") and "filter" not in corpo:
            colecao = caminho.split("/dataObjects:")[0]
            return {
                "dataObjects": [
                    {"name": n} for n in memoria.objetos if n.startswith(colecao + "/")
                ]
            }
        if caminho.endswith(":aggregate"):
            return {"aggregateResults": [{"count": 12}]}
        return memoria(metodo, caminho, corpo)

    assert CONFIG.colecao_de_texto is not None
    for nome, valor in {
        "GCP_PROJECT_ID": CONFIG.projeto,
        "BUSCA_REGIAO": CONFIG.regiao,
        "BUSCA_COLECAO": CONFIG.colecao,
        "BUSCA_COLECAO_DE_TEXTO": CONFIG.colecao_de_texto,
        "BUSCA_COLECAO_DE_MEDIDA": "col-medida",
        "BUSCA_INDICE_DESCRICAO": CONFIG.indice_da_descricao,
        "BUSCA_DIMENSAO": "256",
        "BUSCA_INDICES_LIGADOS": "true",
    }.items():
        monkeypatch.setenv(nome, valor)
    monkeypatch.setattr("api.medir_busca.transporte_http", lambda: transporte)
    assert main(["1", "128"]) == 0
    assert len(colecoes_criadas) == 1 and colecoes_criadas[0].endswith(
        "collectionId=col-medida"
    )
    assert set(memoria.objetos) == {salvo}
