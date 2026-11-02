"""Juntar e dividir pautas (#261): os dois tipos novos de correção, a aprovação, a
reindexação e a reconciliação no reprocessar."""

import json
from typing import Any

from api.tests.test_campos_do_esquema_12 import M12, V12, _corrigir, _modelo, _versao
from api.tests.test_correcoes import AUTORIZACAO, Mundo
from api.tests.test_indexacao import Mundo as MundoDaBusca


def _pauta(id: str, titulo: str, inicio: int, fim: int) -> dict[str, Any]:
    return {
        **M12["pautas"][0],
        "id": id,
        "titulo": titulo,
        "resumo": f"Resumo de {titulo}",
        "inicio_ms": inicio,
        "fim_ms": fim,
    }


TRES = _modelo(
    pautas=[
        _pauta("pau01", "Economia", 0, 20000),
        _pauta("pau02", "Esporte", 20000, 50000),
        _pauta("pau03", "Clima", 50000, 60000),
    ]
)
V3 = _versao(TRES)


def _mundo(modelo: dict[str, Any] = TRES) -> Mundo:
    mundo = Mundo(["editor"])
    mundo.reprocessar(modelo)
    return mundo


def _juntar(mundo: Mundo, ids: list[str], titulo: str = "Geral", **campos: Any) -> Any:
    valor = json.dumps({"ids": ids, "titulo": titulo})
    return _corrigir(mundo, "pauta.juntar", valor, item_id=ids[0], versao=V3, **campos)


def _dividir(mundo: Mundo, em_ms: int = 30000, **campos: Any) -> Any:
    valor = json.dumps({"em_ms": em_ms, "titulos": ["Primeira", "Segunda"]})
    return _corrigir(
        mundo, "pauta.dividir", valor, item_id="pau02", versao=V3, **campos
    )


def _pautas(mundo: Mundo) -> list[tuple[str, str, int, int]]:
    return [
        (p["id"], p["titulo"], p["inicio_ms"], p["fim_ms"])
        for p in mundo.decupagem()["pautas"]
    ]


def test_juntar_duas_pautas_seguidas() -> None:
    mundo = _mundo()

    r = _juntar(mundo, ["pau01", "pau02"])

    assert r.status_code == 201
    assert _pautas(mundo) == [
        ("pau01", "Geral", 0, 50000),
        ("pau03", "Clima", 50000, 60000),
    ]
    junta = mundo.decupagem()["pautas"][0]
    assert junta["origem"] == "revisao"
    assert junta["resumo"] == "Resumo de Economia\nResumo de Esporte"
    [item] = mundo.historico().json()
    assert item["tipo"] == "pauta.juntar"
    assert item["autor_email"] == "ana@redetv.com.br"
    assert item["motivo"] == "sobrenome completo"
    assert item["antes_legivel"] == "Economia 00:00–00:20"
    assert item["depois_legivel"] == "Geral 00:00–00:50"


def test_juntar_tres_pautas_e_desfazer() -> None:
    mundo = _mundo()
    cid = _juntar(mundo, ["pau01", "pau02", "pau03"]).json()["id"]

    assert _pautas(mundo) == [("pau01", "Geral", 0, 60000)]
    mundo.avancar()
    assert mundo.desfazer(cid).status_code == 201
    assert [p[0] for p in _pautas(mundo)] == ["pau01", "pau02", "pau03"]
    assert _pautas(mundo)[0][1] == "Economia"


def test_juntar_pautas_nao_seguidas_ou_sem_item_e_422() -> None:
    mundo = _mundo()

    assert _juntar(mundo, ["pau01", "pau03"]).status_code == 422  # pula a do meio
    assert _juntar(mundo, ["pau02", "pau01"]).status_code == 422  # fora de ordem
    assert _juntar(mundo, ["pau01"]).status_code == 422  # uma só
    assert _juntar(mundo, ["pau01", "pau99"]).status_code == 422  # não existe
    assert _juntar(mundo, ["pau01", "pau02"], titulo=" ").status_code == 422
    assert _juntar(mundo, ["pau01", "pau01"]).status_code == 422
    assert mundo.historico().json() == []


def test_juntar_com_o_item_id_diferente_da_primeira_e_422() -> None:
    mundo = _mundo()
    valor = json.dumps({"ids": ["pau01", "pau02"], "titulo": "Geral"})

    r = _corrigir(mundo, "pauta.juntar", valor, item_id="pau02", versao=V3)

    assert r.status_code == 422


def test_dividir_uma_pauta_em_duas() -> None:
    mundo = _mundo()

    r = _dividir(mundo)

    assert r.status_code == 201
    pautas = _pautas(mundo)
    assert [p[1:] for p in pautas] == [
        ("Economia", 0, 20000),
        ("Primeira", 20000, 30000),
        ("Segunda", 30000, 50000),
        ("Clima", 50000, 60000),
    ]
    assert pautas[2][0].startswith("acr-")
    primeira, segunda = mundo.decupagem()["pautas"][1:3]
    assert (primeira["origem"], segunda["origem"]) == ("revisao", "revisao")
    [item] = mundo.historico().json()
    assert item["antes_legivel"] == "Esporte 00:20–00:50"
    assert item["depois_legivel"] == "Primeira | Segunda (corte em 00:30)"


def test_dividir_e_desfazer() -> None:
    mundo = _mundo()
    cid = _dividir(mundo).json()["id"]
    mundo.avancar()

    assert mundo.desfazer(cid).status_code == 201

    assert _pautas(mundo)[1] == ("pau02", "Esporte", 20000, 50000)
    assert len(_pautas(mundo)) == 3


def test_dividir_fora_da_pauta_ou_com_titulo_vazio_e_422() -> None:
    mundo = _mundo()

    assert _dividir(mundo, 20000).status_code == 422  # na borda
    assert _dividir(mundo, 50000).status_code == 422
    assert _dividir(mundo, 10000).status_code == 422  # fora da pauta
    r = _corrigir(
        mundo,
        "pauta.dividir",
        json.dumps({"em_ms": 30000, "titulos": ["a", " "]}),
        item_id="pau02",
        versao=V3,
    )
    assert r.status_code == 422
    r = _corrigir(
        mundo,
        "pauta.dividir",
        json.dumps({"em_ms": 30000, "titulos": ["a"]}),
        item_id="pau02",
        versao=V3,
    )
    assert r.status_code == 422
    assert mundo.historico().json() == []


def test_os_tipos_novos_estao_no_catalogo_e_podem_exigir_aprovacao() -> None:
    from api.aprovacao import definir_aprovacao_main
    from api.catalogo_de_correcoes import catalogo
    from api.correcoes import RepositorioDeAprovacaoEmMemoria

    tipos = {t.valor: t.rotulo for t in catalogo().tipos}
    repo = RepositorioDeAprovacaoEmMemoria()

    assert tipos["pauta.juntar"] == "Juntar pautas"
    assert tipos["pauta.dividir"] == "Dividir pauta"
    assert definir_aprovacao_main(["pauta.juntar,pauta.dividir"], repo, print) == 0


def test_juntar_com_aprovacao_so_vale_depois_de_aprovar() -> None:
    mundo = _mundo()
    mundo.aprovacao.definir(frozenset({"pauta.juntar"}))

    cid = _juntar(mundo, ["pau01", "pau02"]).json()["id"]

    assert len(_pautas(mundo)) == 3
    mundo.avancar()
    curador = {"Authorization": "Bearer token-curador"}
    r = mundo.cliente.post(f"/v1/jobs/j1/correcoes/{cid}/aprovar", headers=curador)
    assert r.status_code == 201
    assert len(_pautas(mundo)) == 2


def test_dividir_reindexa_o_video() -> None:
    mundo = MundoDaBusca()
    modelo = json.loads(mundo.armazenamento.decupagens["j1"][0])
    pauta = {**_pauta("pau01", "Abertura", 0, 2000), "pessoas": []}
    modelo["pautas"] = [pauta]
    mundo.armazenamento.decupagens["j1"] = [json.dumps(modelo).encode()]
    mundo.reindexar()

    r = mundo.cliente.post(
        "/v1/jobs/j1/correcoes",
        json={
            "tipo": "pauta.dividir",
            "item_id": pauta["id"],
            "valor": json.dumps({"em_ms": 1000, "titulos": ["Um", "Dois"]}),
            "motivo": "são dois assuntos",
            "versao": _versao(modelo),
        },
        headers=AUTORIZACAO,
    )

    assert r.status_code == 201, r.text
    assert mundo.indexacao()["estado"] == "indexado"
    historico = mundo.cliente.get("/v1/jobs/j1/correcoes", headers=AUTORIZACAO).json()
    assert [(i["tipo"], i["na_busca"]) for i in historico] == [
        ("pauta.dividir", "na_busca")
    ]


def test_reprocessar_reaplica_a_juncao_sobre_as_pautas_novas() -> None:
    mundo = _mundo()
    _juntar(mundo, ["pau01", "pau02"])
    mundo.reprocessar(
        _modelo(
            pautas=[
                _pauta("nov1", "Dinheiro", 0, 18000),
                _pauta("nov2", "Bola", 18000, 31000),
                _pauta("nov3", "Gols", 31000, 49000),
                _pauta("nov4", "Tempo", 50000, 60000),
            ]
        )
    )

    assert _pautas(mundo) == [
        ("nov1", "Geral", 0, 49000),
        ("nov4", "Tempo", 50000, 60000),
    ]
    assert mundo.cliente.get("/v1/jobs/j1/fila", headers=AUTORIZACAO).json() == []


def test_reprocessar_reaplica_a_divisao_sobre_a_pauta_nova() -> None:
    mundo = _mundo()
    _dividir(mundo)
    mundo.reprocessar(_modelo(pautas=[_pauta("nov1", "Tudo", 0, 55000)]))

    assert [p[1:] for p in _pautas(mundo)] == [
        ("Primeira", 0, 30000),
        ("Segunda", 30000, 55000),
    ]


def test_reprocessar_sem_pauta_correspondente_deixa_a_juncao_na_fila() -> None:
    mundo = _mundo()
    cid = _juntar(mundo, ["pau01", "pau02"]).json()["id"]
    mundo.reprocessar(_modelo(pautas=[_pauta("nov1", "Longe", 55000, 60000)]))

    assert _pautas(mundo) == [("nov1", "Longe", 55000, 60000)]
    fila = mundo.cliente.get("/v1/jobs/j1/fila", headers=AUTORIZACAO).json()
    assert [i["id"] for i in fila] == [cid]
    assert fila[0]["tipo"] == "pauta.juntar"
    assert fila[0]["candidatos"] == []
    assert fila[0]["depois_legivel"] == "Geral 00:00–00:50"


def test_reprocessar_sem_pauta_a_dividir_deixa_a_divisao_na_fila() -> None:
    mundo = _mundo()
    cid = _dividir(mundo).json()["id"]
    # A pauta nova acaba antes do corte: não há o que dividir.
    mundo.reprocessar(_modelo(pautas=[_pauta("nov1", "Curta", 20000, 25000)]))

    assert _pautas(mundo) == [("nov1", "Curta", 20000, 25000)]
    fila = mundo.cliente.get("/v1/jobs/j1/fila", headers=AUTORIZACAO).json()
    assert [i["id"] for i in fila] == [cid]


def test_a_divisao_ja_feita_pelo_modelo_nao_duplica() -> None:
    mundo = _mundo()
    _dividir(mundo)
    mundo.reprocessar(
        _modelo(
            pautas=[
                _pauta("nov1", "Parte um", 20000, 30100),
                _pauta("nov2", "Parte dois", 30100, 50000),
            ]
        )
    )

    assert [p[1:] for p in _pautas(mundo)] == [
        ("Parte um", 20000, 30100),
        ("Parte dois", 30100, 50000),
    ]
    assert mundo.cliente.get("/v1/jobs/j1/fila", headers=AUTORIZACAO).json() == []


def test_a_juncao_ja_feita_pelo_modelo_nao_vai_para_a_fila() -> None:
    mundo = _mundo()
    _juntar(mundo, ["pau01", "pau02"])
    mundo.reprocessar(_modelo(pautas=[_pauta("nov1", "Tudo junto", 0, 50000)]))

    assert _pautas(mundo) == [("nov1", "Tudo junto", 0, 50000)]
    assert mundo.cliente.get("/v1/jobs/j1/fila", headers=AUTORIZACAO).json() == []


def test_v12_importada_nao_se_perde() -> None:
    assert V12 != V3
