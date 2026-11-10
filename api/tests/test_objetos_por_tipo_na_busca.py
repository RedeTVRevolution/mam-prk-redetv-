"""Tipo canônico na busca e na cópia do BigQuery (#544).

Agrupar por tipo é uma visão: cada ocorrência segue com o seu dono, cor e marca, e o
índice e o BigQuery derivam os registros das ocorrências, não dos atributos agrupados.
"""

import copy
from datetime import UTC, datetime
from typing import Any

import pytest

from api.copia_bigquery import linhas_da_decupagem
from api.decupagem import Decupagem
from api.indice_da_busca import (
    Consulta,
    Filtros,
    IndiceEmMemoria,
    registros_da_decupagem,
)
from api.tests.test_decupagem import decupagem_valida


def _objeto(
    id: str, tipo: str, pessoa: str | None, cor: str, **mais: Any
) -> dict[str, Any]:
    return {
        "id": id,
        "categoria": "roupa",
        "tipo": tipo,
        "cor_base": [cor],
        "pessoa": pessoa,
        "relacao": "veste" if pessoa else None,
        "ocorrencias": [{"inicio_ms": 1000, "fim_ms": 3000}],
        **mais,
    }


def _inventario(nome: str, **mais: Any) -> dict[str, Any]:
    return {
        "nome": nome,
        "categoria": "calcado",
        "cor": "preto",
        "marca": None,
        "caixas": [
            {"quadro": "q/a.jpg", "x": 0.1, "y": 0.1, "largura": 0.2, "altura": 0.2}
        ],
        "destaque": 2,
        **mais,
    }


def _decupagem(versao: str = "1.5") -> Decupagem:
    d = decupagem_valida()
    d["versao_esquema"] = versao
    outra = copy.deepcopy(d["pessoas"][0])
    outra |= {"id": "pes02", "nome": "Beltrana", "catalogo_id": "cat2"}
    d["pessoas"][0]["catalogo_id"] = "cat1"
    d["pessoas"].append(outra)
    d["objetos"] = [
        _objeto("obj01", "camiseta", "pes01", "azul"),
        _objeto("obj02", "blusa", "pes02", "vermelho"),
        _objeto("obj03", "xablau raro", "pes01", "preto"),
        _objeto("obj04", "coisa estranha", "pes02", "preto"),
    ]
    d["planos"][0]["inventario"] = [_inventario("mocassim"), _inventario("tênis")]
    d["inventario_gerado_por"] = {"motor": "florence", "modelo": "x"}
    return Decupagem.model_validate(d)


def _indice(versao: str = "1.5") -> IndiceEmMemoria:
    indice = IndiceEmMemoria()
    indice.gravar("j", registros_da_decupagem("j", _decupagem(versao), None, None))
    return indice


def _achados(indice: IndiceEmMemoria, texto: str, **filtros: Any) -> list[str]:
    consulta = Consulta(texto=texto, filtros=Filtros(tipo="objeto", **filtros))
    return [r.id for r in indice.buscar(consulta)]


@pytest.mark.parametrize("versao", ["1.2", "1.4", "1.5"])
def test_a_busca_casa_o_nome_bruto_sem_tipo_nem_sinonimo(versao: str) -> None:
    indice = _indice(versao)

    # Decisão de 10/11/2026: "tênis" acha só tênis e "mocassim" só mocassim.
    assert _achados(indice, "mocassim") == ["j:inventario:pla001:0"]
    assert _achados(indice, "tênis") == ["j:inventario:pla001:1"]
    # O tipo canônico e os sinônimos não entram no texto: nada de "sapato" nem "camisa".
    assert _achados(indice, "sapato") == []
    assert _achados(indice, "camisa") == []
    assert _achados(indice, "camiseta") == ["j:objeto:obj01:0"]
    assert _achados(indice, "blusa") == ["j:objeto:obj02:0"]


@pytest.mark.parametrize("versao", ["1.2", "1.5"])
def test_nomes_desconhecidos_diferentes_continuam_separados_na_busca_exata(
    versao: str,
) -> None:
    indice = _indice(versao)

    assert _achados(indice, "xablau") == ["j:objeto:obj03:0"]
    assert _achados(indice, "estranha") == ["j:objeto:obj04:0"]


def test_mesmo_tipo_com_donos_e_cores_diferentes_nao_cruza_os_atributos() -> None:
    indice = _indice()

    # Dono da camiseta azul (cat1) com a cor da blusa vermelha: nada.
    assert _achados(indice, "camiseta", dono="cat1", cor_base="vermelho") == []
    assert _achados(indice, "blusa", dono="cat2", cor_base="azul") == []
    assert _achados(indice, "camiseta", dono="cat1", cor_base="azul") == [
        "j:objeto:obj01:0"
    ]
    assert _achados(indice, "blusa", dono="cat2", cor_base="vermelho") == [
        "j:objeto:obj02:0"
    ]


def test_o_registro_guarda_o_texto_bruto_e_o_tipo_canonico_vai_a_parte() -> None:
    objetos = {
        r.id: r
        for r in registros_da_decupagem("j", _decupagem(), None, None)
        if r.tipo == "objeto"
    }

    assert objetos["j:objeto:obj01:0"].tipo_do_objeto == "camiseta"
    assert objetos["j:objeto:obj01:0"].tipo_canonico == "camisa"
    assert objetos["j:objeto:obj03:0"].tipo_canonico == "outro"
    assert objetos["j:inventario:pla001:0"].tipo_do_objeto == "mocassim"
    assert objetos["j:inventario:pla001:0"].tipo_canonico == "sapato"


def test_a_copia_para_o_bigquery_ganha_a_coluna_do_tipo_nos_objetos() -> None:
    linhas = linhas_da_decupagem(
        "j", _decupagem(), None, None, datetime(2026, 11, 10, tzinfo=UTC)
    )

    por_tipo = {
        (x.tipo, x.texto and x.texto.split(",")[0]): x.tipo_canonico
        for x in linhas
        if x.tipo == "objeto"
    }
    assert set(por_tipo.values()) == {"camisa", "outro", "sapato"}
    assert all(x.tipo_canonico is None for x in linhas if x.tipo != "objeto")
