"""Correção de objeto (#304): o item `objeto` e o `objeto.atributos`."""

import json
from typing import Any

import pytest

from api.correcoes import reconciliar, versao_do_modelo
from api.tests.test_correcoes import MODELO, Mundo


def _objeto(id: str, tipo: str, inicio: int, fim: int, **campos: Any) -> dict[str, Any]:
    return {
        "id": id,
        "categoria": "roupa",
        "tipo": tipo,
        "cor_base": ["vermelho"],
        "ocorrencias": [{"inicio_ms": inicio, "fim_ms": fim}],
        **campos,
    }


def _modelo(objetos: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if objetos is None:
        objetos = [
            _objeto("obj01", "vestido", 1000, 5000, pessoa="pes01", relacao="veste")
        ]
    return {**MODELO, "objetos": objetos}


def _versao(modelo: dict[str, Any]) -> str:
    return versao_do_modelo(json.dumps(modelo).encode())


M = _modelo()
V = _versao(M)
CURADOR = {"Authorization": "Bearer token-curador"}
EDITOR = {"Authorization": "Bearer token-bom"}


def _mundo(modelo: dict[str, Any] = M) -> Mundo:
    mundo = Mundo(["editor"])
    mundo.reprocessar(modelo)
    return mundo


def _atributos(**campos: Any) -> str:
    return json.dumps({"tipo": "vestido", "cor_base": ["azul"], **campos})


def _corrigir(mundo: Mundo, valor: str, **campos: Any) -> Any:
    campos.setdefault("versao", V)
    campos.setdefault("item_id", "obj01")
    return mundo.corrigir(tipo="objeto.atributos", valor=valor, **campos)


def _objetos(mundo: Mundo, params: str = "") -> list[dict[str, Any]]:
    return list(mundo.decupagem(params)["objetos"])


def test_atributos_aplicam_e_aparecem_legiveis_no_historico() -> None:
    mundo = _mundo()
    valor = _atributos(
        tipo="saia", cor_base=["azul", "branco"], cor="marinho", marca="X"
    )

    r = _corrigir(mundo, valor)

    assert r.status_code == 201
    [o] = _objetos(mundo)
    assert (o["tipo"], o["cor_base"], o["cor"], o["marca"], o["origem"]) == (
        "saia",
        ["azul", "branco"],
        "marinho",
        "X",
        "revisao",
    )
    assert (o["pessoa"], o["relacao"]) == ("pes01", "veste")
    assert _objetos(mundo, "?versao=modelo")[0]["tipo"] == "vestido"
    [item] = mundo.historico().json()
    assert item["antes_legivel"] == "vestido · vermelho"
    assert item["depois_legivel"] == "saia · azul, branco · marinho · X"


def test_atributos_sem_cor_detalhe_e_marca_apagam_o_que_havia() -> None:
    modelo = _modelo([_objeto("obj01", "vestido", 1000, 5000, cor="vinho", marca="Z")])
    mundo = _mundo(modelo)

    r = _corrigir(mundo, _atributos(), versao=_versao(modelo))

    assert r.status_code == 201
    [o] = _objetos(mundo)
    assert (o["cor"], o["marca"]) == (None, None)


def test_desfazer_devolve_os_atributos_do_modelo() -> None:
    mundo = _mundo()
    cid = _corrigir(mundo, _atributos(tipo="saia")).json()["id"]
    mundo.avancar()

    assert mundo.desfazer(cid).status_code == 201

    assert _objetos(mundo)[0]["tipo"] == "vestido"
    assert "origem" not in _objetos(mundo)[0]


def test_com_aprovacao_so_vale_depois_de_aprovar() -> None:
    mundo = _mundo()
    mundo.aprovacao.definir(frozenset({"objeto.atributos"}))
    r = _corrigir(mundo, _atributos(tipo="saia"))

    assert r.status_code == 201
    assert _objetos(mundo)[0]["tipo"] == "vestido"
    mundo.avancar()
    aprovada = mundo.cliente.post(
        f"/v1/jobs/j1/correcoes/{r.json()['id']}/aprovar", headers=CURADOR
    )
    assert aprovada.status_code == 201
    assert _objetos(mundo)[0]["tipo"] == "saia"


def test_reaplica_numa_versao_nova_mesmo_com_o_id_mudado() -> None:
    mundo = _mundo()
    _corrigir(mundo, _atributos(tipo="saia"))
    novo = _modelo([_objeto("obj07", "vestido", 1200, 5200)])
    mundo.reprocessar(novo)

    [o] = _objetos(mundo)

    assert (o["id"], o["tipo"], o["origem"]) == ("obj07", "saia", "revisao")
    assert mundo.cliente.get("/v1/jobs/j1/fila", headers=EDITOR).json() == []


def test_segue_o_objeto_depois_de_trocar_o_tipo() -> None:
    mundo = _mundo()
    _corrigir(mundo, _atributos(tipo="saia"))
    # A versão nova já traz o tipo certo: nada a fazer, nada na fila.
    novo = _modelo([_objeto("obj01", "saia", 1000, 5000, cor_base=["azul"])])
    mundo.reprocessar(novo)

    assert _objetos(mundo)[0]["tipo"] == "saia"
    assert mundo.cliente.get("/v1/jobs/j1/fila", headers=EDITOR).json() == []


def test_entra_na_fila_ao_reprocessar_sem_objeto_correspondente() -> None:
    mundo = _mundo()
    _corrigir(mundo, _atributos(tipo="saia"))
    novo = _modelo([_objeto("obj01", "carro", 1000, 5000)])
    mundo.reprocessar(novo)

    fila = mundo.cliente.get("/v1/jobs/j1/fila", headers=EDITOR).json()

    assert [f["tipo"] for f in fila] == ["objeto.atributos"]
    assert "origem" not in _objetos(mundo)[0]
    r = reconciliar(novo, _versao(novo), mundo.correcoes.listar("j1"))
    assert [c.tipo for c in r.sem_casar] == ["objeto.atributos"]


def test_objeto_de_mesmo_tipo_sem_sobreposicao_vai_para_a_fila() -> None:
    mundo = _mundo()
    _corrigir(mundo, _atributos(tipo="saia"))
    novo = _modelo([_objeto("obj01", "vestido", 20000, 30000)])
    mundo.reprocessar(novo)

    fila = mundo.cliente.get("/v1/jobs/j1/fila", headers=EDITOR).json()

    assert [f["tipo"] for f in fila] == ["objeto.atributos"]


@pytest.mark.parametrize(
    "valor",
    [
        _atributos(cor_base=["azul", "branco", "preto"]),
        _atributos(cor_base=["azul", "azul"]),
        _atributos(cor_base=["turquesa"]),
        _atributos(tipo=""),
        _atributos(tipo="  "),
        json.dumps({"cor_base": ["azul"]}),
        _atributos(extra="x"),
        _atributos(cor=""),
        "texto solto",
    ],
)
def test_valor_invalido_e_422(valor: str) -> None:
    assert _corrigir(_mundo(), valor).status_code == 422


def test_objeto_inexistente_e_404_ou_422() -> None:
    r = _corrigir(_mundo(), _atributos(), item_id="obj99")

    assert r.status_code in (404, 422)
