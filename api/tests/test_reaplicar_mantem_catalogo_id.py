"""Reaplicar uma Correção leva o `catalogo_id` da original para a nova (#626)."""

from typing import Any

from api.tests.test_catalogo_na_correcao import _pessoa
from api.tests.test_comerciais import COM, VERSAO_COM, _comercial, _mundo
from api.tests.test_correcoes import AUTORIZACAO, MODELO, Mundo
from api.tests.test_correcoes import _pessoa as _pessoa_do_modelo


def _reaplicar(mundo: Mundo, cid: str, item_id: str) -> Any:
    resposta = mundo.cliente.post(
        f"/v1/jobs/j1/fila/{cid}/reaplicar",
        json={"motivo": "revisei", "item_id": item_id},
        headers=AUTORIZACAO,
    )
    assert resposta.status_code == 201
    return resposta.json()


def _gravada(mundo: Mundo, id: str) -> Any:
    return next(c for c in mundo.correcoes.listar("j1") if c.id == id)


def test_reaplicar_a_renomeacao_da_pessoa_mantem_o_vinculo_com_o_catalogo() -> None:
    mundo = Mundo(["editor"])
    ana = mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])
    cid = mundo.corrigir(catalogo_id=ana.id).json()["id"]
    mundo.avancar()
    mundo.reprocessar(
        {**MODELO, "pessoas": [_pessoa_do_modelo("p1", "Carla", 1000, 5000)]}
    )

    nova = _reaplicar(mundo, cid, "p1")

    assert _gravada(mundo, nova["id"]).catalogo_id == ana.id
    assert _pessoa(mundo, "p1")["catalogo_id"] == ana.id
    assert mundo.jobs.obter("j1").pessoas_do_catalogo == [ana.id]  # type: ignore[union-attr]


def test_reaplicar_a_troca_de_marca_mantem_o_vinculo_com_o_catalogo() -> None:
    mundo = _mundo()
    banco = mundo.marcas.acrescentar("Banco Verde", [])
    cid = mundo.corrigir(
        tipo="comercial.marca",
        item_id="com000",
        valor="Banco Verde",
        versao=VERSAO_COM,
        catalogo_id=banco.id,
    ).json()["id"]
    mundo.avancar()
    mundo.reprocessar(
        {
            **COM,
            "comerciais": [
                _comercial("Banco Cinza", 10000, 15000),
                COM["comerciais"][1],
            ],
        }
    )

    nova = _reaplicar(mundo, cid, "com000")

    assert _gravada(mundo, nova["id"]).catalogo_id == banco.id
    marca = next(c for c in mundo.decupagem()["comerciais"] if c["id"] == "com000")
    assert (marca["marca"], marca["catalogo_id"]) == ("Banco Verde", banco.id)
    assert mundo.jobs.obter("j1").marcas_do_catalogo == [banco.id]  # type: ignore[union-attr]
