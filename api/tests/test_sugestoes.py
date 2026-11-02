"""Sugestões que o editor confirma (#152): rota, aceite e recusa, GC de identificação
e trecho sem pauta, e a contagem por tipo."""

import json
from typing import Any

import pytest

from api import sugestoes
from api.correcoes import Ocorrencia
from api.tests.test_correcoes import AUTORIZACAO, Mundo

CURADOR = {"Authorization": "Bearer token-curador"}
DURACAO = 3_600_000
TRECHO_SEM_PAUTA = (2_660_000, 2_959_000)  # 44:20 a 49:19


def _pessoa(id: str, nome: str, inicio: int, fim: int, **listas: Any) -> dict[str, Any]:
    return {
        "id": id,
        "nome": nome,
        "origem": "modelo",
        "na_imagem": [{"inicio_ms": inicio, "fim_ms": fim, "evidencia": "rosto"}],
        "citada_na_fala": [],
        "citada_no_texto": [],
        **listas,
    }


def _pauta(id: str, inicio: int, fim: int) -> dict[str, Any]:
    return {
        "id": id,
        "titulo": f"Pauta {id}",
        "resumo": "Resumo",
        "inicio_ms": inicio,
        "fim_ms": fim,
        "pessoas": [],
        "locais": [],
    }


def _texto(inicio: int, fim: int, tipo: str, texto: str) -> dict[str, Any]:
    return {"inicio_ms": inicio, "fim_ms": fim, "tipo": tipo, "texto": texto}


def _modelo(**mudancas: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "versao_esquema": "1.2",
        "video": {"duracao_ms": DURACAO},
        "pautas": [_pauta("pau01", 0, DURACAO)],
        "pessoas": [],
        "textos_na_tela": [],
    }
    return {**base, **mudancas}


def _clipe4() -> dict[str, Any]:
    """03:31: GC do Leão Lobo sobre um "não identificado"; 03:55: a chamada do Felipe
    Camargo, com o apresentador na imagem."""
    return _modelo(
        pessoas=[
            _pessoa("pes01", "Não identificado, homem de óculos", 211_000, 250_000),
            _pessoa("pes02", "Apresentador", 230_000, 260_000),
        ],
        textos_na_tela=[
            _texto(211_000, 225_000, "gc", "LEÃO LOBO · colunista"),
            _texto(
                235_000, 245_000, "chamada", "Ex-marido Felipe Camargo conta sua versão"
            ),
        ],
    )


def _mundo(modelo: dict[str, Any]) -> Mundo:
    mundo = Mundo(["editor"])
    mundo.reprocessar(modelo)
    return mundo


def _sugestoes(mundo: Mundo, cabecalho: dict[str, str] = AUTORIZACAO) -> Any:
    return mundo.cliente.get("/v1/jobs/j1/sugestoes", headers=cabecalho)


def _abertas(mundo: Mundo) -> list[dict[str, Any]]:
    resposta = _sugestoes(mundo)
    assert resposta.status_code == 200
    corpo: list[dict[str, Any]] = resposta.json()
    return corpo


def _aceitar(mundo: Mundo, sid: str, corpo: dict[str, Any] | None = None) -> Any:
    return mundo.cliente.post(
        f"/v1/jobs/j1/sugestoes/{sid}/aceitar", json=corpo or {}, headers=AUTORIZACAO
    )


def _recusar(mundo: Mundo, sid: str) -> Any:
    return mundo.cliente.post(
        f"/v1/jobs/j1/sugestoes/{sid}/recusar", headers=AUTORIZACAO
    )


def _da_pessoa(mundo: Mundo) -> dict[str, Any]:
    [sugestao] = [s for s in _abertas(mundo) if s["tipo"] == "identificar_pessoa"]
    return sugestao


def _da_pauta(mundo: Mundo) -> list[dict[str, Any]]:
    return [s for s in _abertas(mundo) if s["tipo"] == "pauta_do_trecho"]


def _modelo_com_trecho_sem_pauta() -> dict[str, Any]:
    return _modelo(
        pautas=[
            _pauta("pau01", 0, TRECHO_SEM_PAUTA[0]),
            _pauta("pau02", TRECHO_SEM_PAUTA[1], DURACAO),
        ]
    )


def test_o_gc_sobre_um_nao_identificado_pergunta_quem_e() -> None:
    sugestao = _da_pessoa(_mundo(_clipe4()))

    assert sugestao["pergunta"] == "É Leão Lobo?"
    assert sugestao["contexto"] == "GC às 03:31: LEÃO LOBO · colunista"
    assert (sugestao["inicio_ms"], sugestao["fim_ms"]) == (211_000, 225_000)
    assert sugestao["correcao"] == {
        "tipo": "pessoa.renomear",
        "item_id": "pes01",
        "valor": "Leão Lobo",
        "catalogo_id": None,
        "ocorrencia": None,
    }
    assert sugestao["depois"] == []


def test_a_chamada_nunca_sustenta_uma_sugestao() -> None:
    modelo = _clipe4()
    modelo["textos_na_tela"] = [modelo["textos_na_tela"][1]]  # só a chamada

    assert _abertas(_mundo(modelo)) == []


def test_so_o_gc_com_nome_conta() -> None:
    modelo = _clipe4()
    for tipo in ("tarja", "legenda", "placar", "outro"):
        modelo["textos_na_tela"] = [_texto(211_000, 225_000, tipo, "LEÃO LOBO")]
        assert _abertas(_mundo(modelo)) == []
    for texto in ("AO VIVO 14:32", "", "   ", "VOCÊ NÃO VAI ACREDITAR NISSO, DIZ ELE"):
        modelo["textos_na_tela"] = [_texto(211_000, 225_000, "gc", texto)]
        assert _abertas(_mundo(modelo)) == []


def test_o_gc_fora_do_tempo_do_nao_identificado_nao_gera() -> None:
    modelo = _clipe4()
    modelo["textos_na_tela"] = [_texto(300_000, 310_000, "gc", "LEÃO LOBO")]

    assert _abertas(_mundo(modelo)) == []


def test_sem_nenhum_nao_identificado_ou_com_dois_ao_mesmo_tempo_nao_gera() -> None:
    sem = _clipe4()
    sem["pessoas"][0]["nome"] = "Fulano de Tal"
    dois = _clipe4()
    dois["pessoas"].append(_pessoa("pes03", "Não identificado", 212_000, 220_000))

    assert _abertas(_mundo(sem)) == []
    assert _abertas(_mundo(dois)) == []


def test_nome_ja_na_imagem_no_trecho_nao_gera() -> None:
    modelo = _clipe4()
    modelo["pessoas"].append(_pessoa("pes03", "Leão Lobo", 212_000, 220_000))

    assert _abertas(_mundo(modelo)) == []


def test_o_nome_do_catalogo_vale_e_leva_o_catalogo_id() -> None:
    mundo = _mundo(_clipe4())
    leao = mundo.catalogo.acrescentar("Leão Lobo", "comentarista", [])

    correcao = _da_pessoa(mundo)["correcao"]

    assert (correcao["valor"], correcao["catalogo_id"]) == ("Leão Lobo", leao.id)


def test_a_mencao_no_texto_passa_a_aparicao_depois_de_renomear() -> None:
    modelo = _clipe4()
    modelo["pessoas"][0]["citada_no_texto"] = [
        {"inicio_ms": 212_000, "fim_ms": 224_000, "texto": "LEÃO LOBO · colunista"}
    ]

    [depois] = _da_pessoa(_mundo(modelo))["depois"]

    assert depois == {
        "tipo": "pessoa.mencao_para_aparicao",
        "item_id": "pes01",
        "valor": "LEÃO LOBO · colunista",
        "catalogo_id": None,
        "ocorrencia": {
            "lista": "citada_no_texto",
            "inicio_ms": 212_000,
            "fim_ms": 224_000,
        },
    }


def _com_palpite(nome: str = "Leão Lobo", **extra: Any) -> dict[str, Any]:
    palpite = _pessoa(
        "pes01", nome, 211_000, 250_000, estado_do_nome="palpite", **extra
    )
    return _modelo(
        pessoas=[palpite, _pessoa("pes02", "Apresentador", 230_000, 260_000)]
    )


def _do_palpite(mundo: Mundo) -> list[dict[str, Any]]:
    return [s for s in _abertas(mundo) if s["correcao"]["tipo"] == "pessoa.renomear"]


def test_o_palpite_nao_confirmado_pergunta_se_o_modelo_acertou() -> None:
    [sugestao] = _do_palpite(_mundo(_com_palpite()))

    assert sugestao["tipo"] == "identificar_pessoa"
    assert sugestao["pergunta"] == "O modelo acha que é Leão Lobo. Confirma?"
    assert "sem prova" in sugestao["contexto"]
    assert "03:31" in sugestao["contexto"]
    assert (sugestao["inicio_ms"], sugestao["fim_ms"]) == (211_000, 250_000)
    assert sugestao["correcao"] == {
        "tipo": "pessoa.renomear",
        "item_id": "pes01",
        "valor": "Leão Lobo",
        "catalogo_id": None,
        "ocorrencia": None,
    }


def test_o_contexto_diz_de_onde_veio_o_palpite() -> None:
    [da_analise] = _do_palpite(_mundo(_com_palpite()))
    [do_forte] = _do_palpite(_mundo(_com_palpite(origem="modelo_forte")))

    assert da_analise["contexto"].startswith("Palpite da análise do vídeo")
    assert do_forte["contexto"].startswith("Palpite do modelo forte")


def test_outro_palpite_para_a_mesma_pessoa_e_outra_sugestao() -> None:
    [leao] = _do_palpite(_mundo(_com_palpite()))
    [outro] = _do_palpite(_mundo(_com_palpite("Felipe Bueno")))

    assert leao["id"] != outro["id"]


def test_o_nome_confirmado_nao_gera_sugestao_de_palpite() -> None:
    modelo = _com_palpite()
    modelo["pessoas"][0]["estado_do_nome"] = "confirmado"
    modelo["pessoas"][0]["fontes_do_nome"] = ["referencia"]

    assert _do_palpite(_mundo(modelo)) == []


def test_o_palpite_do_catalogo_leva_o_catalogo_id() -> None:
    mundo = _mundo(_com_palpite())
    leao = mundo.catalogo.acrescentar("Leão Lobo", "comentarista", [])

    [sugestao] = _do_palpite(mundo)

    assert sugestao["correcao"]["catalogo_id"] == leao.id


def test_o_palpite_leva_o_nome_como_esta_no_catalogo() -> None:
    mundo = _mundo(_com_palpite("leao  lobo"))
    leao = mundo.catalogo.acrescentar("Leão Lobo", "comentarista", [])

    [sugestao] = _do_palpite(mundo)

    assert sugestao["pergunta"] == "O modelo acha que é Leão Lobo. Confirma?"
    assert (sugestao["correcao"]["valor"], sugestao["correcao"]["catalogo_id"]) == (
        "Leão Lobo",
        leao.id,
    )


def test_aceitar_o_palpite_confirma_o_nome_pela_revisao() -> None:
    mundo = _mundo(_com_palpite())
    [sugestao] = _do_palpite(mundo)

    resposta = _aceitar(mundo, sugestao["id"])

    assert resposta.status_code == 201
    [item] = mundo.historico().json()
    assert item["motivo"] == "sugestão confirmada pelo editor"
    pessoa = mundo.decupagem()["pessoas"][0]
    assert (pessoa["nome"], pessoa["origem"]) == ("Leão Lobo", "revisao")
    assert pessoa["estado_do_nome"] == "confirmado"
    assert _do_palpite(mundo) == []


def test_recusar_o_palpite_nao_o_sugere_de_novo() -> None:
    mundo = _mundo(_com_palpite())
    [sugestao] = _do_palpite(mundo)

    assert _recusar(mundo, sugestao["id"]).status_code == 204

    assert _do_palpite(mundo) == []
    assert mundo.decupagem()["pessoas"][0]["estado_do_nome"] == "palpite"


# --- Peça citada no visual (#154) ----------------------------------------------------


def _com_visual(visual: str, objetos: list[dict[str, Any]] | None = None) -> Mundo:
    pessoa = _pessoa("pes01", "Sabrina Sato", 10_000, 50_000)
    pessoa["na_imagem"][0]["visual"] = visual
    mundo = _mundo(_modelo(pessoas=[pessoa], objetos=objetos or []))
    mundo.tipos_de_objeto.registrar(
        "j0", {"terno": 3, "camisa": 3, "vestido": 5, "sandália": 2, "óculos de sol": 1}
    )
    return mundo


def _do_visual(mundo: Mundo) -> list[dict[str, Any]]:
    return [s for s in _abertas(mundo) if s["tipo"] == "objeto_do_visual"]


def _objeto_da_sugestao(sugestao: dict[str, Any]) -> dict[str, Any]:
    assert sugestao["correcao"]["tipo"] == "objeto.acrescentar"
    corpo: dict[str, Any] = json.loads(sugestao["correcao"]["valor"])
    return corpo


def test_o_visual_com_dois_tipos_conhecidos_gera_duas_sugestoes() -> None:
    sugestoes_ = _do_visual(_com_visual("terno preto e camisa rosa"))

    assert {s["pergunta"] for s in sugestoes_} == {
        "Acrescentar camisa rosa de Sabrina Sato?",
        "Acrescentar terno preto de Sabrina Sato?",
    }
    por_tipo = {o["tipo"]: o for o in map(_objeto_da_sugestao, sugestoes_)}
    assert por_tipo["terno"]["cor_base"] == ["preto"]
    assert por_tipo["camisa"]["cor_base"] == ["rosa"]
    assert por_tipo["terno"] | {"cor_base": []} == {
        "tipo": "terno",
        "cor_base": [],
        "categoria": "roupa",
        "pessoa": "pes01",
        "relacao": "veste",
        "inicio_ms": 10_000,
        "fim_ms": 50_000,
    }


def test_o_objeto_que_a_pessoa_ja_tem_no_trecho_nao_gera() -> None:
    ja_tem = {
        "id": "obj01",
        "categoria": "roupa",
        "tipo": "terno",
        "cor_base": ["preto"],
        "pessoa": "pes01",
        "relacao": "veste",
        "ocorrencias": [{"inicio_ms": 0, "fim_ms": 20_000}],
    }
    [sugestao] = _do_visual(_com_visual("terno preto e camisa rosa", [ja_tem]))

    assert _objeto_da_sugestao(sugestao)["tipo"] == "camisa"


def test_o_objeto_de_outra_pessoa_ou_de_outro_trecho_nao_impede() -> None:
    de_outra = {
        "id": "obj01",
        "categoria": "roupa",
        "tipo": "terno",
        "cor_base": ["preto"],
        "pessoa": "pes09",
        "relacao": "veste",
        "ocorrencias": [{"inicio_ms": 0, "fim_ms": 20_000}],
    }
    depois = {**de_outra, "id": "obj02", "pessoa": "pes01"}
    depois["ocorrencias"] = [{"inicio_ms": 60_000, "fim_ms": 70_000}]

    assert len(_do_visual(_com_visual("terno preto", [de_outra, depois]))) == 1


def test_acento_maiuscula_e_plural_simples_casam() -> None:
    [sugestao] = _do_visual(_com_visual("SANDALIAS douradas"))

    assert _objeto_da_sugestao(sugestao)["tipo"] == "sandália"
    assert _objeto_da_sugestao(sugestao)["cor_base"] == ["dourado"]


def test_a_categoria_e_a_relacao_vem_do_objeto_ja_visto_no_video() -> None:
    sandalia_de_outra = {
        "id": "obj01",
        "categoria": "calcado",
        "tipo": "sandália",
        "cor_base": ["azul"],
        "pessoa": "pes09",
        "relacao": "calca",
        "ocorrencias": [{"inicio_ms": 0, "fim_ms": 5_000}],
    }
    [sugestao] = _do_visual(_com_visual("sandália", [sandalia_de_outra]))

    objeto = _objeto_da_sugestao(sugestao)
    assert (objeto["categoria"], objeto["relacao"], objeto["cor_base"]) == (
        "calcado",
        "calca",
        [],
    )
    assert sugestao["pergunta"] == "Acrescentar sandália de Sabrina Sato?"


def test_o_tipo_com_varias_palavras_vale_e_nao_repete_o_mais_curto() -> None:
    mundo = _com_visual("óculos de sol escuros")
    mundo.tipos_de_objeto.registrar("j1", {"óculos": 4})

    [sugestao] = _do_visual(mundo)

    assert _objeto_da_sugestao(sugestao)["tipo"] == "óculos de sol"


def test_visual_sem_tipo_conhecido_ou_sem_visual_nao_gera() -> None:
    assert _do_visual(_com_visual("sorridente, de pé")) == []
    assert _do_visual(_mundo(_modelo(pessoas=[_pessoa("p", "A", 0, 1)]))) == []


def test_aceitar_acrescenta_o_objeto_a_pessoa_no_trecho_da_aparicao() -> None:
    mundo = _com_visual("vestido vermelho")
    [sugestao] = _do_visual(mundo)

    resposta = _aceitar(mundo, sugestao["id"])

    assert resposta.status_code == 201
    [objeto] = mundo.decupagem()["objetos"]
    assert (objeto["tipo"], objeto["cor_base"], objeto["pessoa"]) == (
        "vestido",
        ["vermelho"],
        "pes01",
    )
    assert objeto["ocorrencias"] == [{"inicio_ms": 10_000, "fim_ms": 50_000}]
    assert _do_visual(mundo) == []


def test_recusar_o_objeto_do_visual_nao_o_sugere_de_novo() -> None:
    mundo = _com_visual("vestido vermelho")
    [sugestao] = _do_visual(mundo)

    assert _recusar(mundo, sugestao["id"]).status_code == 204
    assert _do_visual(mundo) == []


def test_aceitar_com_outro_tipo_troca_so_o_tipo() -> None:
    mundo = _com_visual("vestido vermelho")
    [sugestao] = _do_visual(mundo)

    assert _aceitar(mundo, sugestao["id"], {"valor": "macacão"}).status_code == 201
    [objeto] = mundo.decupagem()["objetos"]
    assert (objeto["tipo"], objeto["cor_base"]) == ("macacão", ["vermelho"])


def test_trecho_longo_sem_pauta_gera_a_sugestao_de_pauta() -> None:
    [sugestao] = _da_pauta(_mundo(_modelo_com_trecho_sem_pauta()))

    assert sugestao["pergunta"] == "Criar uma pauta de 44:20 a 49:19?"
    assert (sugestao["inicio_ms"], sugestao["fim_ms"]) == TRECHO_SEM_PAUTA
    assert sugestao["correcao"]["tipo"] == "pauta.acrescentar"
    assert sugestao["correcao"]["item_id"] == ""
    proposta = json.loads(sugestao["correcao"]["valor"])
    assert proposta["titulo"] == ""
    assert (proposta["inicio_ms"], proposta["fim_ms"]) == TRECHO_SEM_PAUTA


def test_trecho_de_20_s_nao_gera_e_30_s_geram() -> None:
    curto = _modelo(
        pautas=[_pauta("pau01", 0, 1_000_000), _pauta("pau02", 1_020_000, DURACAO)]
    )
    justo = _modelo(
        pautas=[_pauta("pau01", 0, 1_000_000), _pauta("pau02", 1_030_000, DURACAO)]
    )

    assert _da_pauta(_mundo(curto)) == []
    assert len(_da_pauta(_mundo(justo))) == 1


def test_o_trecho_sem_pauta_no_comeco_ou_no_fim_do_video_tambem_conta() -> None:
    modelo = _modelo(pautas=[_pauta("pau01", 60_000, DURACAO - 45_000)])

    trechos = [(s["inicio_ms"], s["fim_ms"]) for s in _da_pauta(_mundo(modelo))]

    assert trechos == [(0, 60_000), (DURACAO - 45_000, DURACAO)]


def test_pautas_que_se_sobrepoem_cobrem_juntas() -> None:
    modelo = _modelo(
        pautas=[
            _pauta("pau01", 0, 1_000_000),
            _pauta("pau02", 500_000, 2_000_000),
            _pauta("pau03", 2_010_000, DURACAO),
        ]
    )

    assert _da_pauta(_mundo(modelo)) == []


def test_aceitar_cria_a_correcao_com_o_motivo_da_confirmacao() -> None:
    mundo = _mundo(_clipe4())
    sugestao = _da_pessoa(mundo)

    resposta = _aceitar(mundo, sugestao["id"])

    assert resposta.status_code == 201
    [item] = mundo.historico().json()
    assert item["id"] == resposta.json()["id"]
    assert item["tipo"] == "pessoa.renomear"
    assert item["motivo"] == "sugestão confirmada pelo editor"
    assert item["depois"] == "Leão Lobo"
    assert mundo.decupagem()["pessoas"][0]["nome"] == "Leão Lobo"
    assert _abertas(mundo) == []


def test_aceitar_com_outro_nome_usa_o_nome_dado_e_o_motivo_de_correcao() -> None:
    mundo = _mundo(_clipe4())
    mundo.catalogo.acrescentar("Leão Lobo", "comentarista", [])
    sugestao = _da_pessoa(mundo)

    resposta = _aceitar(mundo, sugestao["id"], {"valor": "Leão Lobo Filho"})

    assert resposta.status_code == 201
    [item] = mundo.historico().json()
    assert item["motivo"] == "sugestão corrigida pelo editor"
    assert item["depois"] == "Leão Lobo Filho"
    assert item["catalogo_id"] is None  # o id era do nome proposto, não deste


def test_aceitar_com_o_nome_do_catalogo_liga_o_catalogo_id() -> None:
    mundo = _mundo(_clipe4())
    leao = mundo.catalogo.acrescentar("Leão Lobo", "comentarista", [])

    _aceitar(mundo, _da_pessoa(mundo)["id"])

    [item] = mundo.historico().json()
    assert item["catalogo_id"] == leao.id


def test_aceitar_leva_as_correcoes_seguintes_na_ordem() -> None:
    modelo = _clipe4()
    modelo["pessoas"][0]["citada_no_texto"] = [
        {"inicio_ms": 212_000, "fim_ms": 224_000, "texto": "LEÃO LOBO · colunista"}
    ]
    mundo = _mundo(modelo)

    resposta = _aceitar(mundo, _da_pessoa(mundo)["id"])

    assert resposta.status_code == 201
    assert len(resposta.json()["ids"]) == 2
    # o relógio dos testes é parado: a ordem do histórico empata, a dos ids não
    por_id = {i["id"]: i["tipo"] for i in mundo.historico().json()}
    tipos = [por_id[cid] for cid in resposta.json()["ids"]]
    assert tipos == ["pessoa.renomear", "pessoa.mencao_para_aparicao"]
    assert {i["motivo"] for i in mundo.historico().json()} == {
        "sugestão confirmada pelo editor"
    }
    pessoa = mundo.decupagem()["pessoas"][0]
    assert pessoa["citada_no_texto"] == []
    assert len(pessoa["na_imagem"]) == 2


def test_o_aceite_que_falha_numa_correcao_seguinte_nao_grava_nenhuma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mencao_que_nao_existe(
        pessoa: dict[str, Any], gc: tuple[int, int]
    ) -> list[sugestoes.Proposta]:
        return [
            sugestoes.Proposta(
                tipo="pessoa.mencao_para_aparicao",
                item_id=str(pessoa["id"]),
                valor="LEÃO LOBO",
                ocorrencia=Ocorrencia(
                    lista="citada_no_texto", inicio_ms=1_000, fim_ms=2_000
                ),
            )
        ]

    monkeypatch.setattr(sugestoes, "_mencoes_para_aparicao", mencao_que_nao_existe)
    mundo = _mundo(_clipe4())
    sid = _da_pessoa(mundo)["id"]

    assert _aceitar(mundo, sid).status_code == 422
    assert mundo.historico().json() == []
    assert [s["id"] for s in _abertas(mundo)] == [sid]


def test_a_sugestao_aceita_com_a_correcao_pendente_nao_volta() -> None:
    mundo = _mundo(_clipe4())
    mundo.aprovacao.definir(frozenset({"pessoa.renomear"}))
    sid = _da_pessoa(mundo)["id"]

    assert _aceitar(mundo, sid).status_code == 201
    [item] = mundo.historico().json()
    assert item["exige_aprovacao"] is True
    assert mundo.decupagem()["pessoas"][0]["nome"].startswith("Não identificado")
    assert _abertas(mundo) == []
    assert _aceitar(mundo, sid).status_code == 404


def test_aceitar_a_pauta_pede_o_titulo() -> None:
    mundo = _mundo(_modelo_com_trecho_sem_pauta())
    [sugestao] = _da_pauta(mundo)

    sem_titulo = _aceitar(mundo, sugestao["id"])
    em_branco = _aceitar(mundo, sugestao["id"], {"valor": "   "})

    assert (sem_titulo.status_code, em_branco.status_code) == (422, 422)
    assert mundo.historico().json() == []


def test_aceitar_a_pauta_com_o_titulo_cria_a_pauta_no_trecho() -> None:
    mundo = _mundo(_modelo_com_trecho_sem_pauta())
    [sugestao] = _da_pauta(mundo)

    resposta = _aceitar(mundo, sugestao["id"], {"valor": "Entrevista com o ministro"})

    assert resposta.status_code == 201
    [item] = mundo.historico().json()
    assert item["motivo"] == "sugestão corrigida pelo editor"
    nova = [
        p
        for p in mundo.decupagem()["pautas"]
        if p["titulo"] == "Entrevista com o ministro"
    ]
    assert [(p["inicio_ms"], p["fim_ms"]) for p in nova] == [TRECHO_SEM_PAUTA]
    assert _da_pauta(mundo) == []


def test_recusar_tira_a_sugestao_da_lista_e_nao_muda_a_decupagem() -> None:
    mundo = _mundo(_clipe4())
    sugestao = _da_pessoa(mundo)

    resposta = _recusar(mundo, sugestao["id"])

    assert resposta.status_code == 204
    assert _abertas(mundo) == []
    assert mundo.historico().json() == []
    assert mundo.decupagem()["pessoas"][0]["nome"].startswith("Não identificado")


def test_a_sugestao_recusada_nao_volta_depois_de_reprocessar() -> None:
    mundo = _mundo(_clipe4())
    _recusar(mundo, _da_pessoa(mundo)["id"])

    novo = _clipe4()
    novo["pessoas"][0]["na_imagem"][0]["fim_ms"] = 252_000  # outra versão do modelo
    novo["textos_na_tela"][0]["fim_ms"] = 225_500
    mundo.reprocessar(novo)

    assert _abertas(mundo) == []


def test_o_id_e_estavel_e_muda_com_a_regra_ou_o_trecho() -> None:
    um = _da_pessoa(_mundo(_clipe4()))["id"]
    de_novo = _da_pessoa(_mundo(_clipe4()))["id"]
    outro = _clipe4()
    outro["textos_na_tela"][0]["inicio_ms"] = 212_000
    em_outro_trecho = _da_pessoa(_mundo(outro))["id"]
    pauta = _da_pauta(_mundo(_modelo_com_trecho_sem_pauta()))[0]["id"]

    assert um == de_novo
    assert len({um, em_outro_trecho, pauta}) == 3


def test_a_recusa_vale_so_no_video_dela() -> None:
    mundo = _mundo(_clipe4())
    _recusar(mundo, _da_pessoa(mundo)["id"])

    assert mundo.sugestoes.decididas("j2") == set()


def test_sugestao_inexistente_ou_ja_decidida_da_404() -> None:
    mundo = _mundo(_clipe4())
    sid = _da_pessoa(mundo)["id"]
    _recusar(mundo, sid)

    assert _aceitar(mundo, sid).status_code == 404
    assert _recusar(mundo, sid).status_code == 404
    assert _aceitar(mundo, "nao-existe").status_code == 404


def test_so_quem_edita_ve_e_decide_as_sugestoes() -> None:
    mundo = Mundo(["consulta"])
    mundo.reprocessar(_clipe4())
    sid = "qualquer"

    assert _sugestoes(mundo).status_code == 403
    assert _aceitar(mundo, sid).status_code == 403
    assert _recusar(mundo, sid).status_code == 403
    assert _sugestoes(mundo, {}).status_code == 401


def test_a_contagem_soma_aceitas_e_recusadas_por_tipo() -> None:
    modelo = _modelo_com_trecho_sem_pauta()
    modelo["pessoas"] = _clipe4()["pessoas"]
    modelo["textos_na_tela"] = _clipe4()["textos_na_tela"]
    mundo = _mundo(modelo)

    assert mundo.cliente.get("/v1/sugestoes/contagem", headers=CURADOR).json() == {}

    _aceitar(mundo, _da_pessoa(mundo)["id"])
    _recusar(mundo, _da_pauta(mundo)[0]["id"])

    resposta = mundo.cliente.get("/v1/sugestoes/contagem", headers=CURADOR)
    assert resposta.json() == {
        "identificar_pessoa": {"aceitas": 1, "recusadas": 0},
        "pauta_do_trecho": {"aceitas": 0, "recusadas": 1},
    }


def test_a_contagem_pede_correcao_aprovar() -> None:
    mundo = _mundo(_clipe4())

    assert (
        mundo.cliente.get("/v1/sugestoes/contagem", headers=AUTORIZACAO).status_code
        == 403
    )
