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
    modelo = _modelo(
        [
            _objeto(
                "obj01", "vestido", 1000, 5000, cor="vinho", detalhe="renda", marca="Z"
            )
        ]
    )
    mundo = _mundo(modelo)

    r = _corrigir(mundo, _atributos(), versao=_versao(modelo))

    assert r.status_code == 201
    [o] = _objetos(mundo)
    assert (o["cor"], o["detalhe"], o["marca"]) == (None, None, None)


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


def test_reaplica_no_objeto_que_ja_tem_o_tipo_novo_com_outros_atributos() -> None:
    mundo = _mundo()
    _corrigir(mundo, _atributos(tipo="saia"))
    novo = _modelo([_objeto("obj01", "saia", 1000, 5000, cor_base=["preto"])])
    mundo.reprocessar(novo)

    [o] = _objetos(mundo)
    assert (o["tipo"], o["cor_base"], o["origem"]) == ("saia", ["azul"], "revisao")
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


def test_objeto_inexistente_da_422() -> None:
    r = _corrigir(_mundo(), _atributos(), item_id="obj99")

    assert r.status_code == 422


# objeto.dono (#305)


def _dono(pessoa: str | None, relacao: str | None) -> str:
    return json.dumps({"pessoa": pessoa, "relacao": relacao})


def _corrigir_dono(mundo: Mundo, valor: str, **campos: Any) -> Any:
    campos.setdefault("versao", V)
    campos.setdefault("item_id", "obj01")
    return mundo.corrigir(tipo="objeto.dono", valor=valor, **campos)


def test_dono_troca_a_pessoa_e_a_relacao() -> None:
    mundo = _mundo()

    r = _corrigir_dono(mundo, _dono("pes02", "segura"))

    assert r.status_code == 201
    [o] = _objetos(mundo)
    assert (o["pessoa"], o["relacao"], o["origem"]) == ("pes02", "segura", "revisao")
    assert o["tipo"] == "vestido"
    assert _objetos(mundo, "?versao=modelo")[0]["pessoa"] == "pes01"
    [item] = mundo.historico().json()
    assert item["antes_legivel"] == "dono: pes01 (veste)"


def test_dono_nulo_tira_o_dono() -> None:
    mundo = _mundo()

    assert _corrigir_dono(mundo, _dono(None, None)).status_code == 201

    [o] = _objetos(mundo)
    assert (o["pessoa"], o["relacao"]) == (None, None)


def test_desfazer_devolve_o_dono_do_modelo() -> None:
    mundo = _mundo()
    cid = _corrigir_dono(mundo, _dono(None, None)).json()["id"]
    mundo.avancar()

    assert mundo.desfazer(cid).status_code == 201

    assert (_objetos(mundo)[0]["pessoa"], _objetos(mundo)[0]["relacao"]) == (
        "pes01",
        "veste",
    )
    assert "origem" not in _objetos(mundo)[0]
    desfeita, _ = mundo.historico().json()
    assert (desfeita["antes_legivel"], desfeita["depois_legivel"]) == (
        "sem dono",
        "dono: pes01 (veste)",
    )


def test_dono_com_aprovacao_so_vale_depois_de_aprovar() -> None:
    mundo = _mundo()
    mundo.aprovacao.definir(frozenset({"objeto.dono"}))
    r = _corrigir_dono(mundo, _dono("pes02", "usa"))

    assert r.status_code == 201
    assert _objetos(mundo)[0]["pessoa"] == "pes01"
    mundo.avancar()
    aprovada = mundo.cliente.post(
        f"/v1/jobs/j1/correcoes/{r.json()['id']}/aprovar", headers=CURADOR
    )
    assert aprovada.status_code == 201
    assert _objetos(mundo)[0]["pessoa"] == "pes02"


def test_dono_reaplica_numa_versao_nova() -> None:
    mundo = _mundo()
    _corrigir_dono(mundo, _dono("pes02", "segura"))
    mundo.reprocessar(_modelo([_objeto("obj07", "vestido", 1200, 5200)]))

    [o] = _objetos(mundo)

    assert (o["id"], o["pessoa"], o["relacao"], o["origem"]) == (
        "obj07",
        "pes02",
        "segura",
        "revisao",
    )
    assert mundo.cliente.get("/v1/jobs/j1/fila", headers=EDITOR).json() == []


def test_dono_que_nao_existe_mais_na_versao_nova_nao_muda_o_objeto() -> None:
    mundo = _mundo()
    _corrigir_dono(mundo, _dono("pes02", "segura"))
    novo = {
        **_modelo(
            [_objeto("obj01", "vestido", 1000, 5000, pessoa="pes01", relacao="veste")]
        ),
        "pessoas": [MODELO["pessoas"][0]],
    }
    mundo.reprocessar(novo)

    [o] = _objetos(mundo)

    assert (o["pessoa"], o["relacao"]) == ("pes01", "veste")


@pytest.mark.parametrize(
    "valor",
    [
        _dono("pes99", "veste"),
        _dono("pes02", None),
        _dono(None, "veste"),
        _dono("pes02", "come"),
        json.dumps({"pessoa": "pes02", "relacao": "usa", "extra": 1}),
        json.dumps({"pessoa": "pes02"}),
        "texto solto",
    ],
)
def test_dono_invalido_ou_inexistente_da_422(valor: str) -> None:
    assert _corrigir_dono(_mundo(), valor).status_code == 422


def test_tirar_a_pessoa_da_decupagem_deixa_o_objeto_dela_sem_dono() -> None:
    sozinha = {**MODELO["pessoas"][0], "citada_na_fala": []}
    modelo = {
        **_modelo(
            [_objeto("obj01", "vestido", 20000, 30000, pessoa="pes01", relacao="veste")]
        ),
        "pessoas": [sozinha, MODELO["pessoas"][1]],
    }
    mundo = _mundo(modelo)

    r = mundo.corrigir(
        tipo="pessoa.nao_e",
        item_id="pes01",
        valor="Não identificado",
        ocorrencia={"lista": "na_imagem", "inicio_ms": 1000, "fim_ms": 5000},
        versao=_versao(modelo),
    )

    assert r.status_code == 201
    decupagem = mundo.decupagem()
    assert "pes01" not in [p["id"] for p in decupagem["pessoas"]]
    [o] = decupagem["objetos"]
    assert (o["pessoa"], o["relacao"]) == (None, None)
    _assert_dono_existe(decupagem)


def test_tirar_da_decupagem_o_dono_trocado_deixa_o_objeto_sem_dono() -> None:
    sozinha = {**MODELO["pessoas"][1], "citada_na_fala": []}
    modelo = {**M, "pessoas": [MODELO["pessoas"][0], sozinha]}
    versao = _versao(modelo)
    mundo = _mundo(modelo)
    _corrigir_dono(mundo, _dono("pes02", "segura"), versao=versao)
    mundo.avancar()

    r = mundo.corrigir(
        tipo="pessoa.nao_e",
        item_id="pes02",
        valor="Não identificado",
        ocorrencia={"lista": "na_imagem", "inicio_ms": 7000, "fim_ms": 9000},
        versao=versao,
    )

    assert r.status_code == 201
    decupagem = mundo.decupagem()
    assert "pes02" not in [p["id"] for p in decupagem["pessoas"]]
    [o] = decupagem["objetos"]
    assert (o["pessoa"], o["relacao"]) == (None, None)
    _assert_dono_existe(decupagem)


def _assert_dono_existe(decupagem: dict[str, Any]) -> None:
    """A regra de `_dono_do_objeto_existe` (`api/decupagem.py`): o modelo dos
    testes não traz o esquema inteiro, então ela é conferida à parte."""
    ids = {p["id"] for p in decupagem["pessoas"]}
    assert all(
        o.get("pessoa") is None or o["pessoa"] in ids for o in decupagem["objetos"]
    )


# objeto.nao_existe (#306)


def _nao_existe(mundo: Mundo, **campos: Any) -> Any:
    campos.setdefault("versao", V)
    campos.setdefault("item_id", "obj01")
    return mundo.corrigir(tipo="objeto.nao_existe", valor="nao_existe", **campos)


def test_nao_existe_tira_o_objeto_da_decupagem() -> None:
    modelo = _modelo([*M["objetos"], _objeto("obj02", "chapéu", 2000, 3000)])
    mundo = _mundo(modelo)

    assert _nao_existe(mundo, versao=_versao(modelo)).status_code == 201

    assert [o["id"] for o in _objetos(mundo)] == ["obj02"]
    assert len(_objetos(mundo, "?versao=modelo")) == 2


def test_nao_existe_aparece_legivel_no_historico() -> None:
    mundo = _mundo()
    _nao_existe(mundo)

    [item] = mundo.historico().json()

    assert item["antes_legivel"] == "Objeto na imagem"
    assert item["depois_legivel"] == "Objeto não está na imagem"


def test_desfazer_devolve_o_objeto() -> None:
    mundo = _mundo()
    cid = _nao_existe(mundo).json()["id"]
    assert _objetos(mundo) == []
    mundo.avancar()

    assert mundo.desfazer(cid).status_code == 201

    [o] = _objetos(mundo)
    assert o["id"] == "obj01"
    assert "origem" not in o
    textos = [
        (h["antes_legivel"], h["depois_legivel"]) for h in mundo.historico().json()
    ]
    assert ("Objeto não está na imagem", "Objeto na imagem") in textos


def test_nao_existe_com_aprovacao_so_vale_depois_de_aprovar() -> None:
    mundo = _mundo()
    mundo.aprovacao.definir(frozenset({"objeto.nao_existe"}))
    r = _nao_existe(mundo)

    assert r.status_code == 201
    assert len(_objetos(mundo)) == 1
    mundo.avancar()
    aprovada = mundo.cliente.post(
        f"/v1/jobs/j1/correcoes/{r.json()['id']}/aprovar", headers=CURADOR
    )
    assert aprovada.status_code == 201
    assert _objetos(mundo) == []


def test_nao_existe_reaplica_numa_versao_nova() -> None:
    mundo = _mundo()
    _nao_existe(mundo)
    mundo.reprocessar(_modelo([_objeto("obj07", "vestido", 1200, 5200)]))

    assert _objetos(mundo) == []


def test_nao_existe_em_objeto_inexistente_da_422() -> None:
    assert _nao_existe(_mundo(), item_id="obj99").status_code == 422


@pytest.mark.parametrize("valor", ["existe", "true", "", "texto solto"])
def test_nao_existe_com_outro_valor_da_422(valor: str) -> None:
    r = _mundo().corrigir(
        tipo="objeto.nao_existe", valor=valor, versao=V, item_id="obj01"
    )
    assert r.status_code == 422


@pytest.mark.parametrize(
    ("tipo", "valor"),
    [("objeto.atributos", _atributos()), ("objeto.dono", _dono(None, None))],
)
def test_desfazer_outra_correcao_do_objeto_que_saiu(tipo: str, valor: str) -> None:
    mundo = _mundo()
    cid = mundo.corrigir(tipo=tipo, valor=valor, versao=V, item_id="obj01").json()["id"]
    mundo.avancar()
    nao_existe = _nao_existe(mundo).json()["id"]
    mundo.avancar()

    r = mundo.desfazer(cid)

    assert r.status_code == 201
    assert _objetos(mundo) == []
    mundo.avancar()
    assert mundo.desfazer(nao_existe).status_code == 201
    [o] = _objetos(mundo)
    assert o["tipo"] == "vestido" and o["cor_base"] == ["vermelho"]
    assert (o["pessoa"], o["relacao"]) == ("pes01", "veste")


def test_segundo_nao_existe_no_objeto_que_saiu_da_422() -> None:
    mundo = _mundo()
    _nao_existe(mundo)
    mundo.avancar()

    assert _nao_existe(mundo).status_code == 422


def _novo(**campos: Any) -> str:
    return json.dumps(
        {
            "categoria": "calcado",
            "tipo": "sandália",
            "cor_base": ["vermelho"],
            "pessoa": "pes01",
            "relacao": "calca",
            "inicio_ms": 12000,
            "fim_ms": 19000,
            **campos,
        }
    )


def _acrescentar(mundo: Mundo, valor: str, **campos: Any) -> Any:
    campos.setdefault("versao", V)
    return mundo.corrigir(tipo="objeto.acrescentar", valor=valor, item_id="", **campos)


def test_acrescentar_grava_o_objeto_com_dono_e_desfazer_tira() -> None:
    mundo = _mundo()

    r = _acrescentar(mundo, _novo(cor="vermelho-vivo", marca="Acme"))

    assert r.status_code == 201
    [_, novo] = _objetos(mundo)
    assert novo["id"].startswith("acr-")
    assert (novo["categoria"], novo["tipo"], novo["cor_base"]) == (
        "calcado",
        "sandália",
        ["vermelho"],
    )
    assert (novo["cor"], novo["detalhe"], novo["marca"]) == (
        "vermelho-vivo",
        None,
        "Acme",
    )
    assert (novo["pessoa"], novo["relacao"]) == ("pes01", "calca")
    assert novo["ocorrencias"] == [{"inicio_ms": 12000, "fim_ms": 19000}]
    assert (novo["origem"], novo["acrescentado"]) == ("revisao", True)
    assert len(_objetos(mundo, "?versao=modelo")) == 1
    [item] = mundo.historico().json()
    assert (
        item["depois_legivel"] == "calçado sandália vermelho (dono: pes01) 00:12–00:19"
    )
    mundo.avancar()
    assert mundo.desfazer(r.json()["id"]).status_code == 201
    assert len(_objetos(mundo)) == 1


def test_acrescentar_sem_dono() -> None:
    mundo = _mundo()

    r = _acrescentar(mundo, _novo(pessoa=None, relacao=None))

    assert r.status_code == 201
    novo = _objetos(mundo)[-1]
    assert (novo["pessoa"], novo["relacao"]) == (None, None)
    [item] = mundo.historico().json()
    assert item["depois_legivel"] == "calçado sandália vermelho 00:12–00:19"


def test_acrescentar_com_aprovacao_so_vale_depois_de_aprovar() -> None:
    mundo = _mundo()
    mundo.aprovacao.definir(frozenset({"objeto.acrescentar"}))

    r = _acrescentar(mundo, _novo())

    assert r.status_code == 201
    assert len(_objetos(mundo)) == 1
    mundo.avancar()
    aprovada = mundo.cliente.post(
        f"/v1/jobs/j1/correcoes/{r.json()['id']}/aprovar", headers=CURADOR
    )
    assert aprovada.status_code == 201
    assert _objetos(mundo)[-1]["tipo"] == "sandália"


def test_acrescentar_reaplica_numa_versao_nova() -> None:
    mundo = _mundo()
    _acrescentar(mundo, _novo())
    mundo.reprocessar(_modelo([_objeto("objX", "vestido", 1000, 5000)]))

    assert [o["tipo"] for o in _objetos(mundo)] == ["vestido", "sandália"]


def test_acrescentar_atendida_quando_o_modelo_traz_o_mesmo_tipo_no_trecho() -> None:
    mundo = _mundo()
    _acrescentar(mundo, _novo())
    mundo.reprocessar(
        _modelo([_objeto("obj09", "Sandalia", 12500, 19000, categoria="calcado")])
    )

    assert [o["tipo"] for o in _objetos(mundo)] == ["Sandalia"]


def test_acrescentar_sem_o_dono_na_versao_nova_grava_sem_dono() -> None:
    mundo = _mundo()
    _acrescentar(mundo, _novo())
    sem_pessoas = {**_modelo([_objeto("objX", "vestido", 1000, 5000)]), "pessoas": []}
    mundo.reprocessar(sem_pessoas)

    novo = _objetos(mundo)[-1]

    assert (novo["tipo"], novo["pessoa"], novo["relacao"]) == ("sandália", None, None)
    _assert_dono_existe(mundo.decupagem())


def test_acrescentar_em_decupagem_sem_objetos_da_422() -> None:
    sem_objetos = {k: v for k, v in M.items() if k != "objetos"}
    mundo = _mundo(sem_objetos)

    assert _acrescentar(mundo, _novo(), versao=_versao(sem_objetos)).status_code == 422


@pytest.mark.parametrize(
    "valor",
    [
        _novo(pessoa="pes99"),  # dono que não existe
        _novo(relacao=None),  # pessoa sem relação
        _novo(pessoa=None),  # relação sem pessoa
        _novo(fim_ms=61000),  # além da duração
        _novo(inicio_ms=9000, fim_ms=8000),  # invertido
        _novo(cor_base=["vermelho", "azul", "verde"]),  # 3 cores
        _novo(categoria="coisa"),  # categoria fora da lista
        _novo(tipo=" "),  # tipo vazio
    ],
)
def test_acrescentar_invalido_da_422(valor: str) -> None:
    assert _acrescentar(_mundo(), valor).status_code == 422
