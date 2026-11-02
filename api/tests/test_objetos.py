"""Objetos com atributos e dono (esquema 1.3, #113)."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from api.consolidacao import consolidar
from api.decupagem import (
    CATEGORIAS_DE_OBJETO,
    CORES_BASE,
    RELACOES_DO_OBJETO,
    Decupagem,
    esquema_do_modelo,
)
from api.gemini import instrucao
from api.tempos import aplicar_regra_de_tempos
from api.tests.test_consolidacao import J0, J1, VIDEO, decupagem, pessoa
from api.tests.test_decupagem import decupagem_valida
from api.tests.test_gemini import BOA, TransporteFalso, _mm_ss, _rodar
from api.tests.test_gemini import resposta_em_mm_ss as resposta_do_modelo


def objeto(**mudancas: Any) -> dict[str, Any]:
    return {
        "id": "obj01",
        "categoria": "calcado",
        "tipo": "sandália",
        "cor_base": ["vermelho"],
        "cor": "vermelho vivo",
        "detalhe": "salto alto",
        "marca": None,
        "pessoa": "pes01",
        "relacao": "calca",
        "ocorrencias": [{"inicio_ms": 1_000, "fim_ms": 4_000}],
        **mudancas,
    }


def com_objetos(*objetos: dict[str, Any]) -> dict[str, Any]:
    return {**decupagem_valida(), "versao_esquema": "1.3", "objetos": list(objetos)}


def test_decupagem_com_objetos_passa_no_esquema() -> None:
    d = Decupagem.model_validate(
        com_objetos(
            objeto(),
            objeto(
                id="obj02",
                categoria="em_cena",
                tipo="troféu",
                pessoa=None,
                relacao=None,
                cor_base=["dourado", "preto"],
                cor=None,
                detalhe=None,
            ),
        )
    )

    assert [o.tipo for o in d.objetos] == ["sandália", "troféu"]
    assert d.objetos[0].pessoa == "pes01"


def test_decupagem_12_sem_objetos_continua_valida() -> None:
    d = Decupagem.model_validate(decupagem_valida())

    assert d.objetos == []


@pytest.mark.parametrize(
    "ruim",
    [
        objeto(pessoa="pes99"),
        objeto(categoria="chapéu"),
        objeto(cor_base=["lilás"]),
        objeto(cor_base=["azul", "preto", "branco"]),
        objeto(relacao="rouba"),
        objeto(relacao=None),
        objeto(pessoa=None),
        objeto(ocorrencias=[{"inicio_ms": 5_000, "fim_ms": 1_000}]),
        objeto(ocorrencias=[{"inicio_ms": 0, "fim_ms": 9_999_999}]),
    ],
)
def test_objeto_fora_do_esquema_e_recusado(ruim: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Decupagem.model_validate(com_objetos(ruim))


def test_listas_fechadas_vivem_num_lugar_so_e_vao_para_o_esquema_do_modelo() -> None:
    objeto_do_modelo = esquema_do_modelo()["$defs"]["Objeto"]["properties"]

    assert set(objeto_do_modelo["categoria"]["enum"]) == set(CATEGORIAS_DE_OBJETO)
    assert set(objeto_do_modelo["cor_base"]["items"]["enum"]) == set(CORES_BASE)
    assert "segura" in RELACOES_DO_OBJETO
    assert {
        "roupa",
        "calcado",
        "acessorio",
        "na_mao",
        "em_cena",
        "veiculo",
        "outro",
        "eletronico",
        "produto",
        "animal",
        "alimento",
    } == set(CATEGORIAS_DE_OBJETO)


def test_esquema_do_modelo_traz_as_descricoes_do_esquema_14() -> None:
    esquema = esquema_do_modelo()
    objeto_do_modelo = esquema["$defs"]["Objeto"]["properties"]

    assert "objetos em cena" not in esquema["properties"]["objetos"]["description"]
    assert (
        "só quando nenhuma outra categoria servir"
        in (objeto_do_modelo["categoria"]["description"])
    )
    assert '"carro"' in objeto_do_modelo["tipo"]["description"]
    assert '"celular"' in objeto_do_modelo["tipo"]["description"]
    assert (
        "também entra em `objetos`"
        in (esquema["$defs"]["Plano"]["properties"]["objetos"]["description"])
    )


def test_resposta_simulada_com_carro_sem_dono_e_produto_no_telao_sai_em_14() -> None:
    carro = objeto(
        id="obj01",
        categoria="veiculo",
        tipo="carro",
        pessoa=None,
        relacao=None,
        cor_base=["azul"],
        cor="azul-marinho",
        detalhe=None,
        marca="BYD",
    )
    produto = objeto(
        id="obj02",
        categoria="produto",
        tipo="moto",
        pessoa=None,
        relacao=None,
        detalhe="no telão",
    )

    d = _rodar(TransporteFalso(_resposta_com_objetos(carro, produto)))

    assert d.versao_esquema == "1.4"
    assert [(o.categoria, o.pessoa, o.detalhe) for o in d.objetos] == [
        ("veiculo", None, None),
        ("produto", None, "no telão"),
    ]


def test_decupagem_13_gravada_continua_valida() -> None:
    d = Decupagem.model_validate(com_objetos(objeto()))

    assert d.versao_esquema == "1.3"


@pytest.mark.parametrize("categoria", ["eletronico", "produto", "animal", "alimento"])
def test_categorias_novas_passam_no_esquema(categoria: str) -> None:
    d = Decupagem.model_validate(
        {
            **com_objetos(objeto(categoria=categoria, pessoa=None, relacao=None)),
            "versao_esquema": "1.4",
        }
    )

    assert d.objetos[0].categoria == categoria


def test_instrucao_pede_as_pecas_das_pessoas_com_dono_e_relacao() -> None:
    texto = instrucao(None)

    assert (
        "Para cada pessoa na imagem, registre em objetos o que ela veste, calça e usa"
        in texto
    )
    for verbo in ("veste", "calca", "usa", "segura"):
        assert verbo in texto.split("6. LOCAIS")[0].split("5. ")[1]
    assert "No máximo 5 peças por pessoa em cada aparição" in texto
    assert "Só o que estiver visível" in texto


def test_instrucao_nao_pede_mais_os_objetos_em_cena() -> None:
    secao = instrucao(None).split("6. LOCAIS")[0].split("\n5. ")[1]

    assert "Os objetos de cena não são pedidos aqui" in secao
    for sumiu in (
        "Os dois grupos têm o mesmo peso",
        "os objetos em cena: veículo",
        "Produto mostrado num telão",
        "Todo objeto que você citar em objetos de um plano também entra",
        "comercial tiver a evidência produto",
    ):
        assert sumiu not in secao


def _resposta_com_objetos(*objetos: dict[str, Any]) -> str:
    def em_mm_ss(o: dict[str, Any]) -> dict[str, Any]:
        o = {**o}
        o["ocorrencias"] = [
            {"inicio": _mm_ss(x["inicio_ms"]), "fim": _mm_ss(x["fim_ms"])}
            for x in o["ocorrencias"]
        ]
        return o

    return json.dumps(
        {**resposta_do_modelo(), "objetos": [em_mm_ss(o) for o in objetos]}
    )


def test_resposta_simulada_com_objetos_passa() -> None:
    t = TransporteFalso(_resposta_com_objetos(objeto()))

    d = _rodar(t)

    assert len(t.chamadas) == 1
    [o] = d.objetos
    assert (o.pessoa, o.ocorrencias[0].inicio_ms, o.ocorrencias[0].fim_ms) == (
        "pes01",
        1_000,
        4_000,
    )


def test_resposta_com_pessoa_inexistente_e_refeita() -> None:
    t = TransporteFalso(_resposta_com_objetos(objeto(pessoa="pes99")), BOA)

    _rodar(t)

    assert len(t.chamadas) == 2


def test_instrucao_tem_a_secao_de_objetos_e_a_de_locais() -> None:
    texto = instrucao(None)

    assert "5. PESSOAS: ROUPAS, CALÇADOS E ACESSÓRIOS" in texto
    assert "No máximo 5 peças por pessoa em cada aparição" in texto
    assert "6. LOCAIS E IMAGENS DE APOIO" in texto
    assert "7. COMERCIAIS E MERCHANDISING" in texto


def _objeto_em(pessoa_id: str, inicio: int, fim: int) -> dict[str, Any]:
    return objeto(pessoa=pessoa_id, ocorrencias=[{"inicio_ms": inicio, "fim_ms": fim}])


def test_consolidacao_leva_o_dono_do_objeto_para_a_pessoa_unida() -> None:
    r0 = decupagem(
        pessoas=[pessoa("a", "Ana", [(10_000, 20_000)])],
        objetos=[_objeto_em("a", 12_000, 15_000)],
    )
    r1 = decupagem(
        pessoas=[
            pessoa("x", "Bia", [(310_000, 320_000)]),
            pessoa("b", "ana", [(330_000, 340_000)]),
        ],
        objetos=[_objeto_em("b", 335_000, 338_000)],
    )

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [p.nome for p in d.pessoas] == ["Ana", "Bia"]
    assert [(o.id, o.pessoa, o.ocorrencias[0].inicio_ms) for o in d.objetos] == [
        ("obj01", "pes01", 12_000),
        ("obj02", "pes01", 335_000),
    ]


def test_consolidacao_segue_a_renumeracao_das_pessoas() -> None:
    # A pessoa "a" não tem item mantido e some; "b" passa a ser pes01.
    r0 = decupagem(
        pessoas=[pessoa("b", "Bia", [(10_000, 20_000)])],
        objetos=[_objeto_em("b", 12_000, 15_000)],
    )

    d = consolidar(VIDEO, [(J0, r0)], [])

    assert d.objetos[0].pessoa == "pes01"


def test_consolidacao_descarta_objeto_que_comeca_no_contexto_da_janela() -> None:
    r0 = decupagem(
        pessoas=[pessoa("a", "Ana", [(10_000, 20_000)])],
        objetos=[_objeto_em("a", 12_000, 15_000), _objeto_em("a", 310_000, 320_000)],
    )
    r1 = decupagem(
        pessoas=[pessoa("a", "Ana", [(310_000, 320_000)])],
        objetos=[_objeto_em("a", 310_000, 320_000)],
    )

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [o.ocorrencias[0].inicio_ms for o in d.objetos] == [12_000, 310_000]


def _com_objeto_em(inicio: int, fim: int) -> Decupagem:
    dados = com_objetos(objeto(ocorrencias=[{"inicio_ms": inicio, "fim_ms": fim}]))
    return Decupagem.model_validate(dados)


def test_ocorrencia_do_objeto_ajusta_ao_corte_a_ate_1_s() -> None:
    d = aplicar_regra_de_tempos(_com_objeto_em(1_000, 4_000), [500, 5_000])

    [o] = d.objetos[0].ocorrencias
    assert (o.inicio_ms, o.fim_ms) == (500, 5_000)
    assert (o.inicio_modelo_ms, o.fim_modelo_ms) == (1_000, 4_000)


def test_ocorrencia_do_objeto_nao_ajusta_alem_de_1_s() -> None:
    # Cortes em 0, 3 000 e 5 600: 1 500 e 4 200 estão a mais de 1 s de qualquer um.
    d = aplicar_regra_de_tempos(_com_objeto_em(1_500, 4_200), [3_000, 5_600])

    [o] = d.objetos[0].ocorrencias
    assert (o.inicio_ms, o.fim_ms) == (1_500, 4_200)
    assert o.inicio_modelo_ms is None


def test_ocorrencia_do_objeto_ajusta_a_1_s_exato_e_nao_a_1_001() -> None:
    # 2 000 está a 1 000 do corte 1 000; 4 000 está a 1 001 do corte 5 001.
    d = aplicar_regra_de_tempos(_com_objeto_em(2_000, 4_000), [1_000, 5_001])

    [o] = d.objetos[0].ocorrencias
    assert (o.inicio_ms, o.fim_ms) == (1_000, 4_000)
