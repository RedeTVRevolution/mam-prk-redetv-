"""#547: "Separar pessoa" desfaz uma junção automática, pela camada de Correções."""

import json
from typing import Any

from api.correcoes import (
    Correcao,
    _juntar_as_do_mesmo_nome,
    pares_proibidos,
    versao_do_modelo,
)
from api.tests.test_correcoes import MODELO, Mundo, _pauta

DESCRICAO = "Não identificado, blusa vermelha"
CHAVE_1 = "nao identificado, blusa vermelha@10000-20000"
CHAVE_2 = "nao identificado, blusa vermelha@40000-50000"


def _aparicao(inicio: int, fim: int) -> dict[str, Any]:
    return {"inicio_ms": inicio, "fim_ms": fim, "evidencia": "visto", "papel": None}


def _origem(id: str, chave: str, aparicao: dict[str, Any], **campos: Any) -> dict[str, Any]:
    return {
        "id": id,
        "chave": chave,
        "nome": DESCRICAO,
        "janela": 0,
        "motivo": None,
        "na_imagem": [aparicao],
        "pautas": [],
        "objetos": [],
        **campos,
    }


A1, A2 = _aparicao(10_000, 20_000), _aparicao(40_000, 50_000)
JUNTADA = {
    "id": "pes01",
    "nome": DESCRICAO,
    "origem": "modelo",
    "na_imagem": [A1, A2],
    "citada_na_fala": [],
    "citada_no_texto": [],
    "origens": [
        _origem("pes01", CHAVE_1, A1, pautas=["pau01"]),
        _origem(
            "pes02",
            CHAVE_2,
            A2,
            janela=1,
            motivo="descrição parecida (0.91)",
            pautas=["pau02"],
            objetos=["obj01"],
        ),
    ],
}
OUTRA = {
    "id": "pes03",
    "nome": "Não identificado, senhora de verde",
    "origem": "modelo",
    "na_imagem": [_aparicao(30_000, 35_000)],
    "citada_na_fala": [],
    "citada_no_texto": [],
}
NOVO: dict[str, Any] = {
    **MODELO,
    "pautas": [
        {**_pauta("pau01", "Economia", 0, 30_000), "pessoas": ["pes01"]},
        {**_pauta("pau02", "Esporte", 30_000, 60_000), "pessoas": ["pes01", "pes03"]},
    ],
    "objetos": [
        {
            "id": "obj01",
            "categoria": "roupa",
            "tipo": "blusa",
            "cor_base": ["vermelho"],
            "ocorrencias": [{"inicio_ms": 41_000, "fim_ms": 42_000}],
            "pessoa": "pes01",
            "relacao": "veste",
        }
    ],
    "pessoas": [JUNTADA, OUTRA],
}
VERSAO = versao_do_modelo(json.dumps(NOVO).encode())


def _mundo() -> Mundo:
    mundo = Mundo(["editor"])
    mundo.reprocessar(NOVO)
    return mundo


def _separar(mundo: Mundo, chave: str = CHAVE_2) -> Any:
    resposta = mundo.corrigir(
        tipo="pessoa.separar",
        item_id="pes01",
        valor=chave,
        versao=VERSAO,
        motivo="são duas pessoas",
    )
    mundo.avancar()
    return resposta


def _pessoas(mundo: Mundo) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in mundo.decupagem()["pessoas"]}


def test_separar_devolve_a_origem_com_as_aparicoes_as_pautas_e_os_objetos() -> None:
    mundo = _mundo()

    assert _separar(mundo).status_code == 201

    d = mundo.decupagem()
    pessoas = _pessoas(mundo)
    [nova] = [p for i, p in pessoas.items() if i.startswith("sep-")]
    assert [a["inicio_ms"] for a in pessoas["pes01"]["na_imagem"]] == [10_000]
    assert [a["inicio_ms"] for a in nova["na_imagem"]] == [40_000]
    assert (nova["nome"], nova["origem"]) == (DESCRICAO, "revisao")
    assert pessoas["pes01"]["origens"] == [] and nova["origens"] == []
    # pau02 era da origem separada e da pes03; pau01 só da base
    assert d["pautas"][0]["pessoas"] == ["pes01"]
    assert d["pautas"][1]["pessoas"] == ["pes03", nova["id"]]
    assert d["objetos"][0]["pessoa"] == nova["id"]


def test_desfazer_a_separacao_junta_de_novo() -> None:
    mundo = _mundo()
    cid = _separar(mundo).json()["id"]

    assert mundo.desfazer(cid).status_code == 201

    assert list(_pessoas(mundo)) == ["pes01", "pes03"]
    assert len(_pessoas(mundo)["pes01"]["origens"]) == 2


def test_separar_uma_origem_que_a_pessoa_nao_tem_e_recusado() -> None:
    assert _separar(_mundo(), "nao identificado@1-2").status_code == 422


def test_a_separacao_vale_depois_de_um_reprocessamento_que_junta_de_novo() -> None:
    mundo = _mundo()
    _separar(mundo)
    # O reprocessamento junta as duas outra vez, com o mesmo conteúdo.
    outro = {**NOVO, "pessoas": [{**JUNTADA}, OUTRA], "versao_esquema": "1.2"}
    mundo.reprocessar(outro)

    pessoas = _pessoas(mundo)

    [nova] = [p for i, p in pessoas.items() if i.startswith("sep-")]
    assert [a["inicio_ms"] for a in pessoas["pes01"]["na_imagem"]] == [10_000]
    assert [a["inicio_ms"] for a in nova["na_imagem"]] == [40_000]


def test_pares_proibidos_saem_das_separacoes_em_vigor() -> None:
    mundo = _mundo()
    cid = _separar(mundo).json()["id"]
    correcoes: list[Correcao] = mundo.correcoes.listar("j1")

    assert pares_proibidos(correcoes) == {frozenset({CHAVE_1, CHAVE_2})}

    assert mundo.desfazer(cid).status_code == 201
    assert pares_proibidos(mundo.correcoes.listar("j1")) == set()


def test_pessoas_do_mesmo_nome_separadas_nao_se_juntam_pela_regra_do_nome() -> None:
    def a(id: str) -> dict[str, Any]:
        return {
            "id": id,
            "nome": "Alberto",
            "origem": "modelo",
            "na_imagem": [],
            "citada_na_fala": [],
            "citada_no_texto": [],
        }

    resultado: dict[str, Any] = {
        "pessoas": [a("pes01"), a("sep-1"), a("pes09")],
        "_separadas": [("pes01", "sep-1")],
    }

    _juntar_as_do_mesmo_nome(resultado, {})

    assert [p["id"] for p in resultado["pessoas"]] == ["pes01", "sep-1"]


def test_o_marcador_da_separacao_nao_vaza_para_a_decupagem() -> None:
    mundo = _mundo()
    _separar(mundo)

    assert "_separadas" not in mundo.decupagem()
