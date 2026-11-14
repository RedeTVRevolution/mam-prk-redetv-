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


def test_desfazer_troca_de_nome_com_a_pessoa_que_sumiu_da_decupagem_da_422() -> None:
    """A pes02 é renomeada sem juntar ("Beto") e, depois, de novo para "Ana Souza", o
    nome da pes01: a segunda troca a absorve. Sem a primeira, ela ainda é absorvida,
    então não há pessoa para desfazer: 422. (Absorvida pela própria troca, o desfazer
    separa as duas de novo.)"""
    mundo = Mundo(["editor"])
    cid = mundo.corrigir(item_id="pes02", valor="Beto").json()["id"]
    mundo.avancar()
    assert mundo.corrigir(item_id="pes02", valor="Ana Souza").status_code == 201
    mundo.avancar()
    cliente = TestClient(mundo.cliente.app, raise_server_exceptions=False)

    r = cliente.post(
        f"/v1/jobs/j1/correcoes/{cid}/desfazer",
        json={"motivo": "enganei-me"},
        headers=EDITOR,
    )

    assert (r.status_code, r.json()) == (422, {"detail": "Item inexistente"})
    assert [c.tipo for c in mundo.correcoes.listar("j1")] == [
        "pessoa.renomear",
        "pessoa.renomear",
    ]


def test_desfazer_de_outro_tipo_com_o_item_sumido_continua_gravando() -> None:
    """Caracterização (#605): fora a troca de nome de pessoa, o desfazer com o item fora
    da Decupagem entregue não dá erro: grava o desfazer com antes e depois vazios."""
    mundo = _mundo()
    cid = _corrigir(mundo, _atributos()).json()["id"]
    mundo.avancar()
    # Na mesma versão: o objeto some da Decupagem entregue.
    nao_existe = mundo.corrigir(
        tipo="objeto.nao_existe",
        valor="nao_existe",
        versao=_versao(_modelo()),
        item_id="obj01",
    )
    assert nao_existe.status_code == 201
    mundo.avancar()

    r = TestClient(mundo.cliente.app, raise_server_exceptions=False).post(
        f"/v1/jobs/j1/correcoes/{cid}/desfazer",
        json={"motivo": "enganei-me"},
        headers=EDITOR,
    )

    assert r.status_code == 201
    registradas = mundo.correcoes.listar("j1")
    assert [c.tipo for c in registradas] == [
        "objeto.atributos",
        "objeto.nao_existe",
        "desfazer",
    ]
    assert (registradas[-1].antes, registradas[-1].depois) == ("", "")
