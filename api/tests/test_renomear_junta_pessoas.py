"""#352: trocar o nome para o de outra pessoa do mesmo vídeo junta as duas."""

import json
from typing import Any

from api.correcoes import versao_do_modelo
from api.tests.test_correcoes import MODELO, Mundo, _pauta, _pessoa


def _com_papel(pessoa: dict[str, Any]) -> dict[str, Any]:
    # O esquema 1.2 traz `papel` na aparição; sem ele a correção não se aplica.
    pessoa["na_imagem"][0]["papel"] = None
    return pessoa


PAUTAS = [{**_pauta("pau01", "Economia", 0, 20000), "pessoas": ["pes05", "pes01"]}]
OBJETO = {
    "id": "obj01",
    "categoria": "roupa",
    "tipo": "vestido",
    "cor_base": ["vermelho"],
    "ocorrencias": [{"inicio_ms": 7000, "fim_ms": 9000}],
    "pessoa": "pes05",
    "relacao": "veste",
}
NOVO: dict[str, Any] = {
    **MODELO,
    "pautas": PAUTAS,
    "objetos": [OBJETO],
    "pessoas": [
        _com_papel(_pessoa("pes01", "Alberto", 1000, 5000)),
        _pessoa("pes05", "não identificado", 7000, 9000),
        _pessoa("pes06", "não identificado", 12000, 14000),
    ],
}
VERSAO = versao_do_modelo(json.dumps(NOVO).encode())


def _mundo() -> Mundo:
    mundo = Mundo(["editor"])
    mundo.reprocessar(NOVO)
    return mundo


def _corrigir(mundo: Mundo, tipo: str, item_id: str, valor: str, **campos: Any) -> str:
    resposta = mundo.corrigir(
        tipo=tipo, item_id=item_id, valor=valor, versao=VERSAO, **campos
    )
    assert resposta.status_code == 201, resposta.text
    mundo.avancar()
    return str(resposta.json()["id"])


def _renomear_pes05(mundo: Mundo, nome: str = "Alberto") -> str:
    return _corrigir(mundo, "pessoa.renomear", "pes05", nome)


def _nomes(mundo: Mundo) -> list[str]:
    return [p["nome"] for p in mundo.decupagem()["pessoas"]]


def test_trocar_para_o_nome_de_outra_junta_as_aparicoes_em_ordem() -> None:
    mundo = _mundo()

    _renomear_pes05(mundo, "ALBERTO")

    pessoas = mundo.decupagem()["pessoas"]
    assert [p["id"] for p in pessoas] == ["pes01", "pes06"]
    inicios = [a["inicio_ms"] for a in pessoas[0]["na_imagem"]]
    assert inicios == [1000, 7000]
    assert [m["inicio_ms"] for m in pessoas[0]["citada_na_fala"]] == [5005, 9005]
    assert pessoas[0]["origem"] == "revisao"


def test_pauta_e_objeto_da_absorvida_passam_para_a_que_fica() -> None:
    mundo = _mundo()

    _renomear_pes05(mundo)

    decupagem = mundo.decupagem()
    assert decupagem["pautas"][0]["pessoas"] == ["pes01"]
    assert decupagem["objetos"][0]["pessoa"] == "pes01"


def test_desfazer_a_troca_separa_as_pessoas_de_novo() -> None:
    mundo = _mundo()
    cid = _renomear_pes05(mundo)

    assert mundo.desfazer(cid).status_code == 201

    decupagem = mundo.decupagem()
    assert [p["id"] for p in decupagem["pessoas"]] == ["pes01", "pes05", "pes06"]
    assert decupagem["pautas"][0]["pessoas"] == ["pes05", "pes01"]
    assert decupagem["objetos"][0]["pessoa"] == "pes05"
    # #625: a pessoa absorvida pela própria troca não está na entregue com o desfazer,
    # então o "antes" é o nome que a troca deu.
    desfeita = mundo.correcoes.listar("j1")[-1]
    assert (desfeita.tipo, desfeita.antes, desfeita.depois) == (
        "desfazer",
        "Alberto",
        "não identificado",
    )


def test_correcao_na_absorvida_antes_da_juncao_continua_valendo() -> None:
    mundo = _mundo()
    ocorrencia = {"lista": "na_imagem", "inicio_ms": 7000, "fim_ms": 9000}
    valor = json.dumps({"papel": "apresentador", "visual": None})
    _corrigir(mundo, "aparicao.papel_visual", "pes05", valor, ocorrencia=ocorrencia)

    _renomear_pes05(mundo)

    [ana] = [p for p in mundo.decupagem()["pessoas"] if p["id"] == "pes01"]
    assert ana["na_imagem"][1]["papel"] == "apresentador"


def test_item_tempos_depois_da_juncao_numa_aparicao_da_absorvida_vale() -> None:
    mundo = _mundo()
    _renomear_pes05(mundo)
    ocorrencia = {"lista": "na_imagem", "inicio_ms": 7000, "fim_ms": 9000}

    _corrigir(
        mundo,
        "item.tempos",
        "pes01",
        "7500-9500",
        ocorrencia=ocorrencia,
        tipo_do_item="pessoa",
    )

    [ana] = [p for p in mundo.decupagem()["pessoas"] if p["id"] == "pes01"]
    tempos = [(a["inicio_ms"], a["fim_ms"]) for a in ana["na_imagem"]]
    assert tempos == [(1000, 5000), (7500, 9500)]


def test_duas_pessoas_nao_identificadas_nunca_se_juntam() -> None:
    mundo = _mundo()

    assert _nomes(mundo) == ["Alberto", "não identificado", "não identificado"]


def test_trocar_de_novo_o_nome_da_pessoa_juntada_leva_a_absorvida_junto() -> None:
    mundo = _mundo()
    _renomear_pes05(mundo)

    _corrigir(mundo, "pessoa.renomear", "pes01", "Alberto Souza")

    pessoas = mundo.decupagem()["pessoas"]
    assert [(p["id"], p["nome"]) for p in pessoas] == [
        ("pes01", "Alberto Souza"),
        ("pes06", "não identificado"),
    ]
    assert [a["inicio_ms"] for a in pessoas[0]["na_imagem"]] == [1000, 7000]


def test_fontes_do_nome_da_pessoa_juntada_valem_para_a_absorvida() -> None:
    mundo = _mundo()
    _renomear_pes05(mundo)

    _corrigir(mundo, "pessoa.fontes_do_nome", "pes01", json.dumps(["gc"]))

    [alberto] = [p for p in mundo.decupagem()["pessoas"] if p["id"] == "pes01"]
    assert alberto["fontes_do_nome"] == ["gc"]


def test_a_juncao_fica_com_o_estado_do_nome_da_troca_mais_nova() -> None:
    mundo = _mundo()
    _corrigir(mundo, "pessoa.renomear", "pes01", "Alberto Souza")
    _renomear_pes05(mundo, "Alberto Souza")

    [alberto, _] = mundo.decupagem()["pessoas"]
    assert alberto["id"] == "pes01"
    assert alberto["estado_do_nome"] == "confirmado"
    assert alberto["origem"] == "revisao"


def test_trocar_para_nao_identificado_nao_junta() -> None:
    mundo = _mundo()

    _corrigir(mundo, "pessoa.renomear", "pes01", "não identificado")

    assert [p["id"] for p in mundo.decupagem()["pessoas"]] == [
        "pes01",
        "pes05",
        "pes06",
    ]
