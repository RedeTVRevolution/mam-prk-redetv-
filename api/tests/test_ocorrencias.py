"""Correção de pessoas (#63): aparição e menção."""

import json
from typing import Any

from api.correcoes import versao_do_modelo
from api.decupagem import Pessoa
from api.pessoas import tempo_de_tela_ms
from api.tests.test_correcoes import MODELO, Mundo


def _ocorrencia(lista: str = "na_imagem", inicio: int = 1000, fim: int = 5000) -> Any:
    return {"lista": lista, "inicio_ms": inicio, "fim_ms": fim}


def _nao_e(mundo: Mundo, **campos: Any) -> Any:
    return mundo.corrigir(
        tipo="pessoa.nao_e",
        item_id="pes01",
        valor="Não identificado",
        ocorrencia=_ocorrencia(),
        **campos,
    )


def _pessoa(mundo: Mundo, nome: str) -> dict[str, Any] | None:
    return next((p for p in mundo.decupagem()["pessoas"] if p["nome"] == nome), None)


def test_nao_e_move_a_aparicao_para_um_nao_identificado() -> None:
    mundo = Mundo(["editor"])

    assert _nao_e(mundo).status_code == 201

    ana = _pessoa(mundo, "Ana Souza")
    assert ana is not None and ana["na_imagem"] == []
    assert ana["citada_na_fala"] == [{"inicio_ms": 5005, "fim_ms": 5009}]
    novos = [p for p in mundo.decupagem()["pessoas"] if p["id"].startswith("nid-")]
    assert [(p["nome"], p["origem"]) for p in novos] == [
        ("Não identificado", "revisao")
    ]
    assert novos[0]["na_imagem"][0]["inicio_ms"] == 1000


def test_nao_e_tira_o_tempo_de_tela_da_pessoa() -> None:
    mundo = Mundo(["editor"])
    _nao_e(mundo)

    ana = Pessoa.model_validate(_pessoa(mundo, "Ana Souza"))
    assert tempo_de_tela_ms(ana) == 0


def test_pessoa_sem_nenhuma_ocorrencia_some_da_decupagem() -> None:
    mundo = Mundo(["editor"])
    _nao_e(mundo)
    mundo.corrigir(
        tipo="pessoa.nao_e",
        item_id="pes01",
        valor="Não identificado",
        ocorrencia=_ocorrencia("citada_na_fala", 5005, 5009),
    )

    assert _pessoa(mundo, "Ana Souza") is None


def test_pessoa_que_some_sai_tambem_das_pautas() -> None:
    mundo = Mundo(["editor"])
    pautas = [{**MODELO["pautas"][0], "pessoas": ["pes01", "pes02"]}]
    modelo = {**MODELO, "pautas": [*pautas, MODELO["pautas"][1]]}
    mundo.reprocessar(modelo)
    versao = versao_do_modelo(json.dumps(modelo).encode())
    _nao_e(mundo, versao=versao)
    mundo.corrigir(
        tipo="pessoa.nao_e",
        item_id="pes01",
        valor="Não identificado",
        ocorrencia=_ocorrencia("citada_na_fala", 5005, 5009),
        versao=versao,
    )

    assert mundo.decupagem()["pautas"][0]["pessoas"] == ["pes02"]


def _sandalia(*tempos: tuple[int, int]) -> dict[str, Any]:
    return {
        "id": "obj01",
        "categoria": "calcado",
        "tipo": "sandália",
        "cor_base": ["vermelho"],
        "pessoa": "pes01",
        "relacao": "calca",
        "ocorrencias": [{"inicio_ms": i, "fim_ms": f} for i, f in tempos],
    }


def _com_objeto(mundo: Mundo, objeto: dict[str, Any], **campos: Any) -> str:
    modelo = {**MODELO, **campos, "objetos": [objeto]}
    mundo.reprocessar(modelo)
    return versao_do_modelo(json.dumps(modelo).encode())


def test_nao_e_leva_o_objeto_visto_so_na_aparicao_trocada() -> None:
    mundo = Mundo(["editor"])
    versao = _com_objeto(mundo, _sandalia((1000, 5000)))
    _nao_e(mundo, versao=versao)
    mundo.corrigir(
        tipo="pessoa.nao_e",
        item_id="pes01",
        valor="Não identificado",
        ocorrencia=_ocorrencia("citada_na_fala", 5005, 5009),
        versao=versao,
    )

    [o] = mundo.decupagem()["objetos"]
    assert o["pessoa"].startswith("nid-") and o["relacao"] == "calca"
    ids = {p["id"] for p in mundo.decupagem()["pessoas"]}
    assert o["pessoa"] in ids


def test_nao_e_deixa_com_a_pessoa_o_objeto_visto_noutra_aparicao() -> None:
    mundo = Mundo(["editor"])
    ana = {
        **MODELO["pessoas"][0],
        "na_imagem": [
            *MODELO["pessoas"][0]["na_imagem"],
            {**MODELO["pessoas"][0]["na_imagem"][0], "inicio_ms": 6000, "fim_ms": 8000},
        ],
    }
    pessoas = [ana, *MODELO["pessoas"][1:]]
    versao = _com_objeto(mundo, _sandalia((1000, 5000), (6000, 8000)), pessoas=pessoas)
    _nao_e(mundo, versao=versao)

    [o] = mundo.decupagem()["objetos"]
    assert (o["pessoa"], o["relacao"]) == ("pes01", "calca")


def test_pessoa_que_some_deixa_os_objetos_dela_em_cena() -> None:
    mundo = Mundo(["editor"])
    versao = _com_objeto(mundo, _sandalia((5005, 5009)))
    _nao_e(mundo, versao=versao)
    mundo.corrigir(
        tipo="pessoa.nao_e",
        item_id="pes01",
        valor="Não identificado",
        ocorrencia=_ocorrencia("citada_na_fala", 5005, 5009),
        versao=versao,
    )

    [o] = mundo.decupagem()["objetos"]
    assert (o["pessoa"], o["relacao"]) == (None, None)


def test_aparicao_para_mencao_tira_o_trecho_do_tempo_de_tela() -> None:
    mundo = Mundo(["editor"])

    resposta = mundo.corrigir(
        tipo="pessoa.aparicao_para_mencao",
        item_id="pes01",
        valor="citada_no_texto",
        ocorrencia=_ocorrencia(),
    )

    assert resposta.status_code == 201
    ana = _pessoa(mundo, "Ana Souza")
    assert ana is not None and ana["na_imagem"] == []
    assert ana["citada_no_texto"] == [
        {"inicio_ms": 1000, "fim_ms": 5000, "texto": "rosto"}
    ]
    assert ana["origem"] == "revisao"


def test_mencao_para_aparicao_exige_evidencia_e_entra_no_tempo_de_tela() -> None:
    mundo = Mundo(["editor"])
    base = {
        "tipo": "pessoa.mencao_para_aparicao",
        "item_id": "pes01",
        "ocorrencia": _ocorrencia("citada_na_fala", 5005, 5009),
    }

    assert mundo.corrigir(**base, valor="  ").status_code == 422
    assert mundo.corrigir(**base, valor="rosto no plano aberto").status_code == 201

    ana = _pessoa(mundo, "Ana Souza")
    assert ana is not None and ana["citada_na_fala"] == []
    assert ana["na_imagem"][-1] == {
        "inicio_ms": 5005,
        "fim_ms": 5009,
        "evidencia": "rosto no plano aberto",
    }


def test_mencao_nao_vira_aparicao_pelo_tipo_errado() -> None:
    mundo = Mundo(["editor"])

    assert (
        mundo.corrigir(
            tipo="pessoa.mencao_para_aparicao",
            item_id="pes01",
            valor="rosto",
            ocorrencia=_ocorrencia(),
        ).status_code
        == 422
    )


def test_acrescentar_aparicao_em_pessoa_existente_tem_origem_revisao() -> None:
    mundo = Mundo(["editor"])
    corpo = '{"inicio_ms": 20000, "fim_ms": 22000, "evidencia": "rosto"}'

    resposta = mundo.corrigir(
        tipo="pessoa.acrescentar_aparicao", item_id="pes01", valor=corpo
    )

    assert resposta.status_code == 201
    ana = _pessoa(mundo, "Ana Souza")
    assert ana is not None and ana["origem"] == "revisao"
    assert [a["inicio_ms"] for a in ana["na_imagem"]] == [1000, 20000]


def test_acrescentar_aparicao_em_pessoa_nova_e_fora_da_duracao() -> None:
    mundo = Mundo(["editor"])
    nova = '{"inicio_ms": 20000, "fim_ms": 22000, "evidencia": "GC", "nome": "Beto"}'

    assert (
        mundo.corrigir(
            tipo="pessoa.acrescentar_aparicao", item_id="", valor=nova
        ).status_code
        == 201
    )
    beto = _pessoa(mundo, "Beto")
    assert beto is not None and beto["origem"] == "revisao"
    longe = '{"inicio_ms": 20000, "fim_ms": 99000, "evidencia": "GC", "nome": "C"}'
    assert (
        mundo.corrigir(
            tipo="pessoa.acrescentar_aparicao", item_id="", valor=longe
        ).status_code
        == 422
    )


def test_ocorrencia_que_nao_existe_da_422() -> None:
    mundo = Mundo(["editor"])

    resposta = mundo.corrigir(
        tipo="pessoa.nao_e",
        item_id="pes01",
        valor="Não identificado",
        ocorrencia=_ocorrencia("na_imagem", 30000, 31000),
    )

    assert resposta.status_code == 422


def test_ocorrencia_que_so_encosta_na_borda_nao_e_a_mesma() -> None:
    mundo = Mundo(["editor"])

    resposta = mundo.corrigir(
        tipo="pessoa.nao_e",
        item_id="pes01",
        valor="Não identificado",
        ocorrencia=_ocorrencia("na_imagem", 5000, 6000),
    )

    assert resposta.status_code == 422


def test_tempos_da_ocorrencia() -> None:
    mundo = Mundo(["editor"])

    resposta = mundo.corrigir(
        tipo="item.tempos",
        tipo_do_item="pessoa",
        item_id="pes01",
        valor="1500-4000",
        ocorrencia=_ocorrencia(),
    )

    assert resposta.status_code == 201
    ana = _pessoa(mundo, "Ana Souza")
    assert ana is not None
    assert (ana["na_imagem"][0]["inicio_ms"], ana["na_imagem"][0]["fim_ms"]) == (
        1500,
        4000,
    )


def test_desfazer_devolve_a_ocorrencia() -> None:
    mundo = Mundo(["editor"])
    cid = _nao_e(mundo).json()["id"]
    mundo.avancar()

    assert mundo.desfazer(cid).status_code == 201

    ana = _pessoa(mundo, "Ana Souza")
    assert ana is not None and len(ana["na_imagem"]) == 1
    assert not [p for p in mundo.decupagem()["pessoas"] if p["id"].startswith("nid-")]


def _modelo_novo(inicio: int, fim: int, aparicao: bool = True) -> dict[str, Any]:
    """Reprocessamento: a Ana aparece em outro intervalo (ou só é citada)."""
    pessoa = {
        "id": "pes07",
        "nome": "Ana Souza",
        "origem": "modelo",
        "na_imagem": [{"inicio_ms": inicio, "fim_ms": fim, "evidencia": "rosto"}]
        if aparicao
        else [],
        "citada_na_fala": [{"inicio_ms": 5005, "fim_ms": 5009}],
        "citada_no_texto": [],
    }
    return {**MODELO, "pessoas": [pessoa, MODELO["pessoas"][1]]}


def test_reconciliacao_casa_a_ocorrencia_deslocada_alguns_segundos() -> None:
    mundo = Mundo(["editor"])
    _nao_e(mundo)

    mundo.reprocessar(_modelo_novo(3000, 7000))

    ana = _pessoa(mundo, "Ana Souza")
    assert ana is not None and ana["na_imagem"] == []
    assert [p["id"] for p in mundo.decupagem()["pessoas"] if p["origem"] == "revisao"][
        -1
    ].startswith("nid-")


def test_reconciliacao_manda_para_a_fila_quando_a_aparicao_sumiu() -> None:
    mundo = Mundo(["editor"])
    cid = _nao_e(mundo).json()["id"]

    mundo.reprocessar(_modelo_novo(0, 0, aparicao=False))

    ana = _pessoa(mundo, "Ana Souza")
    assert ana is not None and ana["origem"] == "modelo"
    resposta = mundo.cliente.get(
        "/v1/jobs/j1/fila", headers={"Authorization": "Bearer token-bom"}
    )
    assert [i["id"] for i in resposta.json()] == [cid]
    # A Ana nova não tem a aparição: reaplicar nela não mudaria nada.
    assert resposta.json()[0]["candidatos"] == []


def test_aparicao_acrescentada_que_o_modelo_passa_a_trazer_nao_duplica() -> None:
    mundo = Mundo(["editor"])
    corpo = '{"inicio_ms": 20000, "fim_ms": 22000, "evidencia": "GC", "nome": "Beto"}'
    mundo.corrigir(tipo="pessoa.acrescentar_aparicao", item_id="", valor=corpo)
    beto = {
        "id": "pes09",
        "nome": "Beto",
        "origem": "modelo",
        "na_imagem": [{"inicio_ms": 20100, "fim_ms": 22000, "evidencia": "rosto"}],
        "citada_na_fala": [],
        "citada_no_texto": [],
    }

    mundo.reprocessar({**MODELO, "pessoas": [*MODELO["pessoas"], beto]})

    pessoas = [p for p in mundo.decupagem()["pessoas"] if p["nome"] == "Beto"]
    assert len(pessoas) == 1 and len(pessoas[0]["na_imagem"]) == 1


def test_o_modelo_cru_nao_muda_e_tela_de_tempo_cai() -> None:
    mundo = Mundo(["editor"])
    _nao_e(mundo)

    cru = mundo.decupagem("?versao=modelo")

    assert cru["pessoas"][0]["na_imagem"][0]["inicio_ms"] == 1000
    ana = Pessoa.model_validate(_pessoa(mundo, "Ana Souza"))
    assert tempo_de_tela_ms(ana) == 0
