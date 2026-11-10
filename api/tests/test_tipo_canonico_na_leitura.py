"""O tipo canônico na leitura (#544): o dicionário no acervo antigo, depois das Correções."""

import json
from typing import Any

import pytest

from api.correcoes import decupagem_entregue, versao_do_modelo
from api.decupagem import Decupagem
from api.indexacao import _so_o_esquema
from api.tests.test_correcoes import Mundo
from api.tests.test_correcoes_de_objeto import (
    _atributos,
    _corrigir,
    _modelo,
    _objeto,
    _objetos,
    _versao,
)
from api.tests.test_decupagem import decupagem_valida


def _inventario(nome: str, **mais: Any) -> dict[str, Any]:
    return {
        "nome": nome,
        "categoria": "roupa",
        "cor": None,
        "marca": None,
        "caixas": [
            {"quadro": "q/a.jpg", "x": 0.1, "y": 0.1, "largura": 0.2, "altura": 0.2}
        ],
        "destaque": 1,
        **mais,
    }


def _entregue(modelo: dict[str, Any]) -> dict[str, Any]:
    versao = versao_do_modelo(json.dumps(modelo).encode())
    return decupagem_entregue(modelo, versao, [])


@pytest.mark.parametrize("esquema", ["1.2", "1.3", "1.4"])
def test_acervo_antigo_ganha_o_tipo_pelo_dicionario_sem_reprocessar(
    esquema: str,
) -> None:
    modelo = decupagem_valida()
    modelo["versao_esquema"] = esquema
    modelo["objetos"] = [
        _objeto("obj01", "camiseta", 1000, 5000),
        _objeto("obj02", "xablau raro", 1000, 5000),
    ]
    modelo["planos"][0]["inventario"] = [
        _inventario("blusa"),
        _inventario("xablau raro"),
    ]
    modelo["inventario_gerado_por"] = {"motor": "florence", "modelo": "x"}

    entregue = _entregue(modelo)

    assert [o["tipo_canonico"] for o in entregue["objetos"]] == ["camisa", "outro"]
    assert [i["tipo_canonico"] for i in entregue["planos"][0]["inventario"]] == [
        "camisa",
        "outro",
    ]
    # O texto bruto fica como estava e a Decupagem entregue valida.
    assert [o["tipo"] for o in entregue["objetos"]] == ["camiseta", "xablau raro"]
    Decupagem.model_validate(_so_o_esquema(Decupagem, entregue))


def test_tipo_gravado_da_lista_vale_e_o_fora_da_lista_cai_no_dicionario() -> None:
    modelo = decupagem_valida()
    modelo["objetos"] = [
        _objeto("obj01", "blusa de seda", 1000, 5000, tipo_canonico="camisa"),
        _objeto("obj02", "camiseta", 1000, 5000, tipo_canonico="tipo_que_saiu"),
    ]

    entregue = _entregue(modelo)

    assert [o["tipo_canonico"] for o in entregue["objetos"]] == ["camisa", "camisa"]


def test_a_cor_dentro_do_nome_nao_impede_o_tipo() -> None:
    modelo = decupagem_valida()
    modelo["objetos"] = [_objeto("obj01", "carro vermelho", 1000, 5000)]

    assert _entregue(modelo)["objetos"][0]["tipo_canonico"] == "carro"


def test_correcao_do_tipo_bruto_refaz_o_tipo_canonico_depois_de_aplicada() -> None:
    modelo = _modelo([_objeto("obj01", "vestido", 1000, 5000, tipo_canonico="vestido")])
    mundo = Mundo(["editor"])
    mundo.reprocessar(modelo)

    r = _corrigir(mundo, _atributos(tipo="saia"), versao=_versao(modelo))

    assert r.status_code == 201
    [o] = _objetos(mundo)
    assert (o["tipo"], o["tipo_canonico"]) == ("saia", "saia")
    # A versão do modelo segue crua, e a correção de um valor fora da lista cai em `outro`.
    assert _objetos(mundo, "?versao=modelo")[0]["tipo_canonico"] == "vestido"
    mundo.avancar()
    r = _corrigir(mundo, _atributos(tipo="coisa nunca vista"), versao=_versao(modelo))
    assert r.status_code == 201
    assert _objetos(mundo)[0]["tipo_canonico"] == "outro"
