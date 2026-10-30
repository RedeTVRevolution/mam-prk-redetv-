"""Correção de comerciais (#62): marca, tipo, tempos e inserção acrescentada."""

import json
from typing import Any

import pytest

from api.correcoes import Correcao, aplicar, fila, reconciliar, versao_do_modelo
from api.tests.test_correcoes import (
    AUTORIZACAO,
    BASE,
    MODELO,
    Mundo,
)


def _comercial(
    marca: str, inicio: int, fim: int, tipo: str = "patrocinio_vinheta"
) -> dict[str, Any]:
    return {
        "marca": marca,
        "tipo": tipo,
        "inicio_ms": inicio,
        "fim_ms": fim,
        "evidencia": "logo no canto",
    }


COM = {
    **MODELO,
    "comerciais": [
        _comercial("Banco Azul", 10000, 15000),
        _comercial("Refri Cola", 30000, 35000, "intervalo"),
    ],
}
VERSAO_COM = versao_do_modelo(json.dumps(COM).encode())


def _mundo(papeis: list[Any] | None = None) -> Mundo:
    mundo = Mundo(papeis or ["editor"])
    mundo.reprocessar(COM)
    return mundo


def _corrigir(mundo: Mundo, tipo: str, valor: str, item_id: str = "com000") -> Any:
    return mundo.corrigir(tipo=tipo, item_id=item_id, valor=valor, versao=VERSAO_COM)


def _novo_comercial(**campos: Any) -> str:
    return json.dumps(
        {
            "marca": "Loja Sol",
            "tipo": "merchan_apresentador",
            "inicio_ms": 20000,
            "fim_ms": 22000,
            "evidencia": "apresentador cita a loja",
            **campos,
        }
    )


def _acrescentar(mundo: Mundo, valor: str | None = None) -> Any:
    return mundo.corrigir(
        tipo="comercial.acrescentar",
        item_id="",
        valor=valor or _novo_comercial(),
        versao=VERSAO_COM,
    )


def test_decupagem_traz_id_e_origem_modelo_nos_comerciais() -> None:
    comerciais = _mundo().decupagem()["comerciais"]

    assert [(c["id"], c["origem"]) for c in comerciais] == [
        ("com000", "modelo"),
        ("com001", "modelo"),
    ]


def test_corrigir_marca_tipo_e_tempos_aparece_na_decupagem() -> None:
    mundo = _mundo()

    assert _corrigir(mundo, "comercial.marca", "Banco Verde").status_code == 201
    assert _corrigir(mundo, "comercial.tipo", "marca_incidental").status_code == 201
    assert mundo.corrigir(
        tipo="item.tempos",
        tipo_do_item="comercial",
        item_id="com000",
        valor="11000-14000",
        versao=VERSAO_COM,
    ).json()["id"]

    [c, outro] = mundo.decupagem()["comerciais"]
    assert (c["marca"], c["tipo"], c["inicio_ms"], c["fim_ms"]) == (
        "Banco Verde",
        "marca_incidental",
        11000,
        14000,
    )
    assert c["origem"] == "revisao"
    assert outro["origem"] == "modelo"


def test_item_tempos_de_comercial_precisa_dizer_o_tipo_do_item() -> None:
    mundo = _mundo()

    sem = mundo.corrigir(
        tipo="item.tempos", item_id="com000", valor="1-2", versao=VERSAO_COM
    )
    com = mundo.corrigir(
        tipo="item.tempos",
        tipo_do_item="comercial",
        item_id="com000",
        valor="1-2",
        versao=VERSAO_COM,
    )

    assert (sem.status_code, com.status_code) == (422, 201)


def test_tipo_de_comercial_fora_da_lista_da_422() -> None:
    mundo = _mundo()

    assert _corrigir(mundo, "comercial.tipo", "outro").status_code == 422
    assert mundo.correcoes.listar("j1") == []


def test_tempos_do_comercial_alem_da_duracao_da_422() -> None:
    mundo = _mundo()

    resposta = mundo.corrigir(
        tipo="item.tempos",
        tipo_do_item="comercial",
        item_id="com000",
        valor="0-60001",
        versao=VERSAO_COM,
    )

    assert resposta.status_code == 422


def test_correcao_de_comercial_guarda_antes_depois_e_ancora() -> None:
    mundo = _mundo()

    _corrigir(mundo, "comercial.marca", "Banco Verde")

    [c] = mundo.correcoes.listar("j1")
    assert (c.antes, c.depois) == ("Banco Azul", "Banco Verde")
    assert (c.ancora.tipo_do_item, c.ancora.identidade) == (
        "comercial",
        "banco azul|patrocinio_vinheta",
    )
    assert (c.ancora.inicio_ms, c.ancora.fim_ms) == (10000, 15000)


def test_comercial_inexistente_da_422() -> None:
    assert (
        _corrigir(_mundo(), "comercial.marca", "X", item_id="com099").status_code == 422
    )


def test_acrescentar_poe_o_comercial_na_decupagem_em_ordem_de_inicio() -> None:
    mundo = _mundo()

    assert _acrescentar(mundo).status_code == 201

    comerciais = mundo.decupagem()["comerciais"]
    assert [c["marca"] for c in comerciais] == ["Banco Azul", "Loja Sol", "Refri Cola"]
    novo = comerciais[1]
    assert (novo["origem"], novo["tipo"], novo["evidencia"]) == (
        "revisao",
        "merchan_apresentador",
        "apresentador cita a loja",
    )
    assert novo["acrescentado"] is True
    assert (novo["inicio_ms"], novo["fim_ms"]) == (20000, 22000)


@pytest.mark.parametrize(
    "campos",
    [
        {"tipo": "outro"},
        {"marca": ""},
        {"marca": "a\nb"},
        {"inicio_ms": 22001},
        {"fim_ms": 60001},
        {"evidencia": "x" * 201},
    ],
)
def test_acrescentar_invalido_da_422(campos: dict[str, Any]) -> None:
    mundo = _mundo()

    assert _acrescentar(mundo, _novo_comercial(**campos)).status_code == 422
    assert mundo.correcoes.listar("j1") == []


def test_acrescentar_que_nao_e_json_da_422() -> None:
    assert _acrescentar(_mundo(), "Loja Sol").status_code == 422


def test_desfazer_o_acrescentado_o_tira_da_decupagem() -> None:
    mundo = _mundo()
    cid = _acrescentar(mundo).json()["id"]
    mundo.avancar()

    assert mundo.desfazer(cid).status_code == 201

    assert len(mundo.decupagem()["comerciais"]) == 2


def test_modelo_cru_nao_traz_id_nem_acrescentado() -> None:
    mundo = _mundo()
    _acrescentar(mundo)

    cru = mundo.decupagem("?versao=modelo")

    assert len(cru["comerciais"]) == 2
    assert "id" not in cru["comerciais"][0]


# --- Reconciliação ---


def _antiga(tipo: str, depois: str, **campos: Any) -> Correcao:
    base: dict[str, Any] = {
        "id": "c1",
        "job_id": "j1",
        "autor_uid": "u1",
        "autor_email": "a@x",
        "criada_em": BASE,
        "motivo": "m",
        "tipo": tipo,
        "item_id": "com000",
        "antes": "Banco Azul",
        "depois": depois,
        "ancora": {
            "versao": "velha",
            "tipo_do_item": "comercial",
            "identidade": "banco azul|patrocinio_vinheta",
            "inicio_ms": 10000,
            "fim_ms": 15000,
        },
        **campos,
    }
    return Correcao(**base)


def _com_banco(*intervalos: tuple[int, int]) -> dict[str, Any]:
    return {
        **COM,
        "comerciais": [_comercial("BANCO  azul", i, f) for i, f in intervalos],
    }


def test_casa_pela_marca_normalizada_e_tipo_com_intervalo_sobreposto() -> None:
    novo = _com_banco((12000, 16000))
    c = _antiga("comercial.marca", "Banco Verde")

    r = reconciliar(novo, "nova", [c])

    assert [(x.id, x.item_id) for x in r.casadas] == [("c1", "com000")]
    entregue = aplicar(novo, "nova", [c])
    assert entregue["comerciais"][0]["marca"] == "Banco Verde"


def test_dois_candidatos_vao_para_a_fila() -> None:
    novo = _com_banco((11000, 12000), (13000, 14000))
    c = _antiga("comercial.marca", "Banco Verde")

    r = reconciliar(novo, "nova", [c])

    assert [x.id for x in r.sem_casar] == ["c1"]
    [item] = fila(novo, "nova", [c])
    assert [x.item_id for x in item.candidatos] == ["com000", "com001"]
    assert aplicar(novo, "nova", [c])["comerciais"][0]["marca"] == "BANCO  azul"


def test_sem_intervalo_sobreposto_vai_para_a_fila() -> None:
    novo = _com_banco((40000, 41000))

    r = reconciliar(novo, "nova", [_antiga("comercial.marca", "Banco Verde")])

    assert [x.id for x in r.sem_casar] == ["c1"]


def _acrescentada(**campos: Any) -> Correcao:
    return _antiga(
        "comercial.acrescentar",
        _novo_comercial(marca="Banco Azul", tipo="patrocinio_vinheta"),
        item_id="acr-c1",
        antes="",
        **campos,
    )


def test_acrescentado_atendido_nao_duplica() -> None:
    novo = _com_banco((10500, 14000))
    c = _acrescentada()

    r = reconciliar(novo, "nova", [c])

    assert [x.id for x in r.atendidas] == ["c1"]
    assert r.sem_casar == []
    entregue = aplicar(novo, "nova", [c])
    assert len(entregue["comerciais"]) == 1
    assert entregue["comerciais"][0]["origem"] == "modelo"
    assert fila(novo, "nova", [c]) == []


def test_acrescentado_que_o_modelo_nao_viu_continua_acrescentado() -> None:
    novo = {**COM, "comerciais": [_comercial("Outra", 40000, 41000)]}
    c = _acrescentada()

    entregue = aplicar(novo, "nova", [c])

    assert [x["marca"] for x in entregue["comerciais"]] == ["Banco Azul", "Outra"]
    assert entregue["comerciais"][0]["acrescentado"] is True
    assert fila(novo, "nova", [c]) == []


def test_acrescentado_de_versao_antiga_ainda_se_desfaz() -> None:
    mundo = _mundo()
    cid = _acrescentar(mundo).json()["id"]
    mundo.avancar()
    mundo.reprocessar({**COM, "comerciais": []})

    assert mundo.desfazer(cid).status_code == 201

    assert mundo.decupagem()["comerciais"] == []


def test_reaplicar_tempos_de_comercial_da_fila() -> None:
    mundo = _mundo()
    cid = mundo.corrigir(
        tipo="item.tempos",
        tipo_do_item="comercial",
        item_id="com000",
        valor="11000-14000",
        versao=VERSAO_COM,
    ).json()["id"]
    mundo.avancar()
    mundo.reprocessar(_com_banco((10500, 11000), (13000, 14500)))

    [item] = mundo.cliente.get("/v1/jobs/j1/fila", headers=AUTORIZACAO).json()
    assert item["id"] == cid
    resposta = mundo.cliente.post(
        f"/v1/jobs/j1/fila/{cid}/reaplicar",
        json={"item_id": "com001", "motivo": "é este"},
        headers=AUTORIZACAO,
    )

    assert resposta.status_code == 201
    c = mundo.decupagem()["comerciais"][1]
    assert (c["inicio_ms"], c["fim_ms"]) == (11000, 14000)
    assert c["origem"] == "revisao"
