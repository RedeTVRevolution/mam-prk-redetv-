"""Correção dos campos novos do esquema 1.2 (#75): texto na tela, tom, fontes do
nome, papel e visual."""

import json
from typing import Any

from api.correcoes import aplicar, reconciliar, versao_do_modelo
from api.tests.test_correcoes import MODELO, Mundo


def _texto(id_ini: int, fim: int, texto: str, tipo: str = "gc") -> dict[str, Any]:
    return {"inicio_ms": id_ini, "fim_ms": fim, "tipo": tipo, "texto": texto}


def _modelo(**mudancas: Any) -> dict[str, Any]:
    pessoas = json.loads(json.dumps(MODELO["pessoas"]))
    for p in pessoas:
        p["fontes_do_nome"] = ["gc"]
        for a in p["na_imagem"]:
            a["papel"], a["visual"] = "entrevistado", None
    pautas = [{**p, "tom": "informativo"} for p in MODELO["pautas"]]
    return {
        **MODELO,
        "pessoas": pessoas,
        "pautas": pautas,
        "textos_na_tela": [_texto(0, 3000, "Ana Souza"), _texto(8000, 9000, "Placar")],
        **mudancas,
    }


M12 = _modelo()
V12 = versao_do_modelo(json.dumps(M12).encode())


def _mundo(modelo: dict[str, Any] = M12) -> Mundo:
    mundo = Mundo(["editor"])
    mundo.reprocessar(modelo)
    return mundo


def _versao(modelo: dict[str, Any]) -> str:
    return versao_do_modelo(json.dumps(modelo).encode())


def _corrigir(mundo: Mundo, tipo: str, valor: str, **campos: Any) -> Any:
    versao = campos.pop("versao", V12)
    return mundo.corrigir(tipo=tipo, valor=valor, versao=versao, **campos)


OCORRENCIA = {"lista": "na_imagem", "inicio_ms": 1000, "fim_ms": 5000}


def test_tom_da_pauta_vem_com_origem_revisao_e_desfaz() -> None:
    mundo = _mundo()

    cid = _corrigir(mundo, "pauta.tom", "polemico", item_id="pau01").json()["id"]

    p1, p2 = mundo.decupagem()["pautas"]
    assert (p1["tom"], p1["origem"]) == ("polemico", "revisao")
    assert (p2["tom"], p2["origem"]) == ("informativo", "modelo")
    [item] = mundo.historico().json()
    assert (item["antes"], item["depois"], item["estado"]) == (
        "informativo",
        "polemico",
        "ativa",
    )
    mundo.avancar()
    assert mundo.desfazer(cid).status_code == 201
    assert mundo.decupagem()["pautas"][0]["tom"] == "informativo"


def test_tom_fora_da_lista_e_422() -> None:
    mundo = _mundo()

    assert _corrigir(mundo, "pauta.tom", "polêmico", item_id="pau01").status_code == 422
    assert (
        _corrigir(mundo, "pauta.tom", "comercial", item_id="pau01").status_code == 201
    )


def test_tom_longo_ou_com_controle_e_422() -> None:
    mundo = _mundo()

    assert _corrigir(mundo, "pauta.tom", "x" * 201, item_id="pau01").status_code == 422
    assert _corrigir(mundo, "pauta.tom", "a\nb", item_id="pau01").status_code == 422


def test_fontes_do_nome_trocam_a_lista_e_aceitam_vazia() -> None:
    mundo = _mundo()

    resposta = _corrigir(
        mundo, "pessoa.fontes_do_nome", '["fala", "rosto"]', item_id="pes01"
    )

    assert resposta.status_code == 201
    ana = mundo.decupagem()["pessoas"][0]
    assert (ana["fontes_do_nome"], ana["origem"]) == (["rosto", "fala"], "revisao")
    [item] = mundo.historico().json()
    assert (json.loads(item["antes"]), json.loads(item["depois"])) == (
        ["gc"],
        ["rosto", "fala"],
    )
    mundo.avancar()
    assert (
        _corrigir(mundo, "pessoa.fontes_do_nome", "[]", item_id="pes01").status_code
        == 201
    )
    assert mundo.decupagem()["pessoas"][0]["fontes_do_nome"] == []


def test_fontes_do_nome_invalidas_sao_422() -> None:
    mundo = _mundo()

    for valor in ['["rosto","rosto"]', '["olho"]', '"rosto"', "x"]:
        r = _corrigir(mundo, "pessoa.fontes_do_nome", valor, item_id="pes01")
        assert r.status_code == 422, valor


def test_fontes_do_nome_desfazer_volta_a_lista_anterior() -> None:
    mundo = _mundo()
    cid = _corrigir(
        mundo, "pessoa.fontes_do_nome", '["rosto"]', item_id="pes01"
    ).json()["id"]

    mundo.avancar()
    assert mundo.desfazer(cid).status_code == 201

    ana = mundo.decupagem()["pessoas"][0]
    assert ana["fontes_do_nome"] == ["gc"]


def test_papel_e_visual_da_aparicao() -> None:
    mundo = _mundo()
    valor = json.dumps({"papel": "apresentador", "visual": "terno azul"})

    resposta = _corrigir(
        mundo,
        "aparicao.papel_visual",
        valor,
        item_id="pes01",
        ocorrencia=OCORRENCIA,
    )

    assert resposta.status_code == 201
    ana = mundo.decupagem()["pessoas"][0]
    assert ana["na_imagem"][0]["papel"] == "apresentador"
    assert ana["na_imagem"][0]["visual"] == "terno azul"
    assert ana["origem"] == "revisao"
    [item] = mundo.historico().json()
    assert json.loads(item["antes"]) == {"papel": "entrevistado", "visual": None}
    assert json.loads(item["depois"]) == {
        "papel": "apresentador",
        "visual": "terno azul",
    }
    mundo.avancar()
    assert mundo.desfazer(item["id"]).status_code == 201
    assert mundo.decupagem()["pessoas"][0]["na_imagem"][0]["papel"] == "entrevistado"


def test_papel_e_visual_aceitam_null_e_rejeitam_o_resto() -> None:
    mundo = _mundo()

    def corrigir(valor: Any, ocorrencia: Any = OCORRENCIA) -> int:
        r = _corrigir(
            mundo,
            "aparicao.papel_visual",
            json.dumps(valor),
            item_id="pes01",
            ocorrencia=ocorrencia,
        )
        return int(r.status_code)

    assert corrigir({"papel": None, "visual": None}) == 201
    assert corrigir({"papel": "x"}) == 422
    assert corrigir({"papel": "", "visual": None}) == 422
    assert corrigir({"papel": "x" * 201, "visual": None}) == 422
    assert corrigir({"papel": "x", "visual": None, "outro": 1}) == 422
    assert (
        corrigir(
            {"papel": "x", "visual": None}, {**OCORRENCIA, "lista": "citada_na_fala"}
        )
        == 422
    )
    # a ocorrência tem de existir
    assert (
        corrigir(
            {"papel": "x", "visual": None},
            {**OCORRENCIA, "inicio_ms": 30000, "fim_ms": 31000},
        )
        == 422
    )


def test_texto_na_tela_ganha_id_posicional_e_origem() -> None:
    d = _mundo().decupagem()

    assert [(t["id"], t["origem"]) for t in d["textos_na_tela"]] == [
        ("txt000", "modelo"),
        ("txt001", "modelo"),
    ]


def test_corrigir_texto_e_tipo_do_texto_na_tela() -> None:
    mundo = _mundo()
    valor = json.dumps({"tipo": "tarja", "texto": "Ana Souza Lima"})

    resposta = _corrigir(mundo, "texto_na_tela.texto", valor, item_id="txt000")

    assert resposta.status_code == 201
    t0, t1 = mundo.decupagem()["textos_na_tela"]
    assert (t0["tipo"], t0["texto"], t0["origem"]) == (
        "tarja",
        "Ana Souza Lima",
        "revisao",
    )
    assert t1["origem"] == "modelo"
    assert (
        mundo.decupagem("?versao=modelo")["textos_na_tela"][0]["texto"] == "Ana Souza"
    )
    [item] = mundo.historico().json()
    assert json.loads(item["antes"]) == {"texto": "Ana Souza", "tipo": "gc"}
    mundo.avancar()
    assert mundo.desfazer(item["id"]).status_code == 201
    assert mundo.decupagem()["textos_na_tela"][0]["texto"] == "Ana Souza"


def test_texto_na_tela_com_tipo_desconhecido_ou_vazio_e_422() -> None:
    mundo = _mundo()

    for valor in [
        {"tipo": "banner", "texto": "x"},
        {"tipo": "gc", "texto": " "},
        {"tipo": "gc"},
    ]:
        r = _corrigir(mundo, "texto_na_tela.texto", json.dumps(valor), item_id="txt000")
        assert r.status_code == 422


def test_acrescentar_texto_na_tela_e_desfazer() -> None:
    mundo = _mundo()
    valor = json.dumps(_texto(4000, 6000, "Ao vivo", "logo"))

    resposta = _corrigir(mundo, "texto_na_tela.acrescentar", valor)

    assert resposta.status_code == 201
    textos = mundo.decupagem()["textos_na_tela"]
    assert [t["texto"] for t in textos] == ["Ana Souza", "Ao vivo", "Placar"]
    assert (textos[1]["origem"], textos[1]["tipo"]) == ("revisao", "logo")
    assert not any(
        t["texto"] == "Ao vivo"
        for t in mundo.decupagem("?versao=modelo")["textos_na_tela"]
    )
    [item] = mundo.historico().json()
    assert (item["tipo"], json.loads(item["depois"])["texto"]) == (
        "texto_na_tela.acrescentar",
        "Ao vivo",
    )
    mundo.avancar()
    assert mundo.desfazer(resposta.json()["id"]).status_code == 201
    assert [t["texto"] for t in mundo.decupagem()["textos_na_tela"]] == [
        "Ana Souza",
        "Placar",
    ]


def test_acrescentar_texto_alem_da_duracao_ou_invertido_e_422() -> None:
    mundo = _mundo()

    for valor in [_texto(59000, 61000, "x"), _texto(5000, 4000, "x")]:
        r = _corrigir(mundo, "texto_na_tela.acrescentar", json.dumps(valor))
        assert r.status_code == 422


def test_tempos_do_texto_na_tela() -> None:
    mundo = _mundo()

    r = _corrigir(
        mundo, "item.tempos", "500-3500", item_id="txt000", tipo_do_item="texto_na_tela"
    )

    assert r.status_code == 201
    t0 = mundo.decupagem()["textos_na_tela"][0]
    assert (t0["inicio_ms"], t0["fim_ms"], t0["origem"]) == (500, 3500, "revisao")
    assert (
        _corrigir(
            mundo,
            "item.tempos",
            "500-70000",
            item_id="txt000",
            tipo_do_item="texto_na_tela",
        ).status_code
        == 422
    )


def test_decupagem_sem_os_campos_novos_da_422_nunca_500() -> None:
    antigo = {k: v for k, v in MODELO.items()}
    mundo = _mundo(antigo)
    versao = _versao(antigo)
    pedidos: list[tuple[str, str, dict[str, Any]]] = [
        ("pauta.tom", "x", {"item_id": "pau01"}),
        ("pessoa.fontes_do_nome", "[]", {"item_id": "pes01"}),
        (
            "aparicao.papel_visual",
            json.dumps({"papel": None, "visual": None}),
            {"item_id": "pes01", "ocorrencia": OCORRENCIA},
        ),
        (
            "texto_na_tela.texto",
            json.dumps({"tipo": "gc", "texto": "x"}),
            {"item_id": "txt000"},
        ),
        ("texto_na_tela.acrescentar", json.dumps(_texto(0, 10, "x")), {}),
        (
            "item.tempos",
            "0-10",
            {"item_id": "txt000", "tipo_do_item": "texto_na_tela"},
        ),
    ]
    for tipo, valor, campos in pedidos:
        r = _corrigir(mundo, tipo, valor, versao=versao, **campos)
        assert r.status_code == 422, tipo


def test_reconcilia_texto_unico_com_sobreposicao_e_mesmo_texto_normalizado() -> None:
    mundo = _mundo()
    valor = json.dumps({"tipo": "tarja", "texto": "Ana Souza Lima"})
    cid = _corrigir(mundo, "texto_na_tela.texto", valor, item_id="txt000").json()["id"]
    novo = _modelo(
        textos_na_tela=[_texto(100, 3200, "ANA  souza"), _texto(8000, 9000, "Placar")]
    )
    mundo.reprocessar(novo)

    d = mundo.decupagem()

    assert d["textos_na_tela"][0]["texto"] == "Ana Souza Lima"
    assert d["textos_na_tela"][0]["origem"] == "revisao"
    assert (
        mundo.cliente.get(
            "/v1/jobs/j1/fila", headers={"Authorization": "Bearer token-bom"}
        ).json()
        == []
    )
    assert cid


def test_dois_candidatos_de_texto_vao_para_a_fila() -> None:
    mundo = _mundo()
    valor = json.dumps({"tipo": "tarja", "texto": "Ana Souza Lima"})
    _corrigir(mundo, "texto_na_tela.texto", valor, item_id="txt000")
    novo = _modelo(
        textos_na_tela=[_texto(0, 2000, "Ana Souza"), _texto(1500, 3000, "Ana Souza")]
    )
    mundo.reprocessar(novo)

    fila = mundo.cliente.get(
        "/v1/jobs/j1/fila", headers={"Authorization": "Bearer token-bom"}
    ).json()

    assert [f["tipo"] for f in fila] == ["texto_na_tela.texto"]
    assert [c["item_id"] for c in fila[0]["candidatos"]] == ["txt000", "txt001"]
    assert all(t["origem"] == "modelo" for t in mundo.decupagem()["textos_na_tela"])


def test_texto_com_outro_texto_ou_sem_sobreposicao_vai_para_a_fila() -> None:
    mundo = _mundo()
    valor = json.dumps({"tipo": "tarja", "texto": "Ana Souza Lima"})
    _corrigir(mundo, "texto_na_tela.texto", valor, item_id="txt000")
    novo = _modelo(textos_na_tela=[_texto(0, 3000, "Outra coisa")])
    mundo.reprocessar(novo)

    versao = _versao(novo)
    r = reconciliar(novo, versao, mundo.correcoes.listar("j1"))

    assert [c.tipo for c in r.sem_casar] == ["texto_na_tela.texto"]


def test_texto_acrescentado_ja_trazido_pelo_modelo_nao_duplica() -> None:
    mundo = _mundo()
    _corrigir(
        mundo,
        "texto_na_tela.acrescentar",
        json.dumps(_texto(4000, 6000, "Ao vivo", "logo")),
    )
    novo = _modelo(
        textos_na_tela=[*M12["textos_na_tela"], _texto(4100, 6000, "AO VIVO", "logo")]
    )
    mundo.reprocessar(novo)

    textos = mundo.decupagem()["textos_na_tela"]

    assert [t["texto"] for t in textos].count("AO VIVO") == 1
    assert "Ao vivo" not in [t["texto"] for t in textos]


def test_texto_acrescentado_e_reaplicado_em_nova_versao() -> None:
    mundo = _mundo()
    _corrigir(
        mundo,
        "texto_na_tela.acrescentar",
        json.dumps(_texto(4000, 6000, "Ao vivo", "logo")),
    )
    mundo.reprocessar(_modelo(textos_na_tela=[]))

    assert [t["texto"] for t in mundo.decupagem()["textos_na_tela"]] == ["Ao vivo"]


def test_fontes_e_papel_visual_sobrevivem_a_nova_versao() -> None:
    mundo = _mundo()
    _corrigir(mundo, "pessoa.fontes_do_nome", '["rosto"]', item_id="pes01")
    _corrigir(
        mundo,
        "aparicao.papel_visual",
        json.dumps({"papel": "apresentador", "visual": None}),
        item_id="pes01",
        ocorrencia=OCORRENCIA,
    )
    novo = _modelo(pautas=[{**p, "resumo": "novo"} for p in M12["pautas"]])
    mundo.reprocessar(novo)

    ana = mundo.decupagem()["pessoas"][0]

    assert ana["fontes_do_nome"] == ["rosto"]
    assert ana["na_imagem"][0]["papel"] == "apresentador"


def test_aplicar_direto_nao_altera_o_modelo() -> None:
    mundo = _mundo()
    _corrigir(mundo, "pauta.tom", "polemico", item_id="pau01")

    entregue = aplicar(M12, V12, mundo.correcoes.listar("j1"))

    assert entregue["pautas"][0]["tom"] == "polemico"
    assert M12["pautas"][0]["tom"] == "informativo"


def test_os_tipos_novos_podem_exigir_aprovacao() -> None:
    from api.aprovacao import definir_aprovacao_main
    from api.correcoes import RepositorioDeAprovacaoEmMemoria

    repo = RepositorioDeAprovacaoEmMemoria()
    tipos = [
        "pauta.tom",
        "pessoa.fontes_do_nome",
        "aparicao.papel_visual",
        "texto_na_tela.texto",
        "texto_na_tela.acrescentar",
    ]

    assert definir_aprovacao_main([",".join(tipos)], repo, lambda _: None) == 0
    assert repo.tipos() == set(tipos)
