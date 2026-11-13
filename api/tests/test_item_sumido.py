"""Reaplicar da fila uma Correção cujo item sumiu da Decupagem (#605, Q5 do #602)."""

from fastapi.testclient import TestClient

from api.tests.test_correcoes import Mundo
from api.tests.test_correcoes_de_objeto import (
    EDITOR,
    _atributos,
    _corrigir,
    _modelo,
    _mundo,
    _objeto,
    _versao,
)


def _reaplicar_no_objeto_que_saiu() -> tuple[Mundo, str, TestClient]:
    """A Correção de atributos cai na fila (dois candidatos); um deles é marcado
    como não existente, e some da Decupagem entregue."""
    mundo = _mundo()
    cid = _corrigir(mundo, _atributos(tipo="saia")).json()["id"]
    mundo.avancar()
    novo = _modelo(
        [
            _objeto("obj01", "vestido", 1000, 3000),
            _objeto("obj02", "vestido", 2000, 6000),
        ]
    )
    mundo.reprocessar(novo)
    nao_existe = mundo.corrigir(
        tipo="objeto.nao_existe",
        valor="nao_existe",
        versao=_versao(novo),
        item_id="obj01",
    )
    assert nao_existe.status_code == 201
    mundo.avancar()
    return mundo, cid, TestClient(mundo.cliente.app, raise_server_exceptions=False)


def test_reaplicar_no_item_que_sumiu_da_decupagem_da_422() -> None:
    mundo, cid, cliente = _reaplicar_no_objeto_que_saiu()

    r = cliente.post(
        f"/v1/jobs/j1/fila/{cid}/reaplicar",
        json={"motivo": "revisei", "item_id": "obj01"},
        headers=EDITOR,
    )

    assert (r.status_code, r.json()) == (422, {"detail": "Item inexistente"})
    # nada gravado: a Correção segue na fila
    assert [
        f["id"] for f in mundo.cliente.get("/v1/jobs/j1/fila", headers=EDITOR).json()
    ] == [cid]
