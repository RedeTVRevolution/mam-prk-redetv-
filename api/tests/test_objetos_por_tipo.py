"""Objetos por tipo canônico (#544): esquema, conversão e junção no plano."""

from typing import Any

from api.decupagem import (
    CaixaDoQuadro,
    Decupagem,
    ObjetoDoInventario,
    esquema_do_modelo,
)
from api.inventario import _esquema, RespostaConvertida, RespostaVista, unir_repetidos
from api.taxonomia_de_objetos import OPCOES_DE_TIPO
from api.tests.test_decupagem import decupagem_valida
from api.tests.test_inventario import (
    COM_SOFA,
    TransporteFalso,
    convertido,
    decupagem,
    resposta,
)
from api.inventario import converter_do_florence


def caixa(x: float = 0.1) -> CaixaDoQuadro:
    return CaixaDoQuadro(quadro="q/a.jpg", x=x, y=0.1, largura=0.2, altura=0.2)


def objeto(nome: str, **mais: Any) -> ObjetoDoInventario:
    base: dict[str, Any] = {
        "nome": nome,
        "categoria": "roupa",
        "cor": "azul",
        "marca": None,
        "caixas": [caixa()],
        "destaque": 1,
    }
    return ObjetoDoInventario.model_validate(base | mais)


def test_os_esquemas_do_modelo_trazem_o_tipo_em_enum_ao_lado_do_texto_livre() -> None:
    analise = esquema_do_modelo()["$defs"]["Objeto"]["properties"]
    assert analise["tipo_canonico"]["enum"] == OPCOES_DE_TIPO
    assert "tipo" in analise  # o texto livre continua
    for modelo in (RespostaConvertida, RespostaVista):
        esquema = _esquema(modelo)
        descrito = esquema["$defs"][
            "ObjetoConvertido" if modelo is RespostaConvertida else "ObjetoVisto"
        ]
        assert descrito["properties"]["tipo_canonico"]["enum"] == OPCOES_DE_TIPO
        assert "tipo_canonico" in descrito["required"]
        assert "nome" in descrito["properties"]


def test_decupagem_antiga_sem_o_campo_novo_continua_valida() -> None:
    d = Decupagem.model_validate(decupagem_valida())
    assert all(o.tipo_canonico == "outro" for o in d.objetos)


def test_a_conversao_grava_o_tipo_escolhido_e_o_dicionario_cobre_o_outro() -> None:
    transporte = TransporteFalso(
        resposta(
            {
                "plano": 0,
                "objetos": [
                    convertido("blusa", ["p0q0o0"], tipo_canonico="camisa"),
                    convertido(
                        "camiseta", ["p0q0r0"], tipo_canonico="outro", cor="azul"
                    ),
                ],
            }
        )
    )
    inventarios = converter_do_florence(
        decupagem(["q/a.jpg"]), COM_SOFA, transporte=transporte, modelo="m", job_id="j1"
    )
    assert [(i.nome, i.tipo_canonico) for i in inventarios[0]] == [
        ("blusa", "camisa"),
        ("camiseta", "camisa"),
    ]


def test_nome_sem_tipo_seguro_fica_em_outro_com_o_nome_bruto() -> None:
    transporte = TransporteFalso(
        resposta(
            {
                "plano": 0,
                "objetos": [
                    convertido("xablau raro", ["p0q0o0"], tipo_canonico="outro")
                ],
            }
        )
    )
    (item,) = converter_do_florence(
        decupagem(["q/a.jpg"]), COM_SOFA, transporte=transporte, modelo="m", job_id="j1"
    )[0]
    assert (item.nome, item.tipo_canonico) == ("xablau raro", "outro")


def test_unir_repetidos_agrupa_pelo_tipo_e_nao_pelo_nome() -> None:
    juntos = unir_repetidos(
        [
            objeto("camiseta", tipo_canonico="camisa"),
            objeto("blusa", tipo_canonico="camisa", caixas=[caixa(0.5)], destaque=3),
            objeto("camisa"),  # sem o tipo gravado: o dicionário resolve
        ]
    )
    assert len(juntos) == 1
    assert len(juntos[0].caixas) == 3
    assert juntos[0].destaque == 3
    assert juntos[0].nome == "camiseta"  # o texto bruto do primeiro fica


def test_mesmo_tipo_com_cor_ou_marca_diferente_mantem_cada_combinacao() -> None:
    juntos = unir_repetidos(
        [
            objeto("camisa", tipo_canonico="camisa", cor="azul", marca="Nike"),
            objeto("camiseta", tipo_canonico="camisa", cor="branco", marca="Nike"),
            objeto("blusa", tipo_canonico="camisa", cor="azul", marca="Adidas"),
            objeto("camisa", tipo_canonico="camisa", cor="azul", marca=None),
        ]
    )
    assert [(i.cor, i.marca, len(i.caixas)) for i in juntos] == [
        ("azul", "Nike", 2),  # a sem marca entra na que tem
        ("branco", "Nike", 1),
        ("azul", "Adidas", 1),
    ]


def test_dois_nomes_desconhecidos_diferentes_continuam_separados() -> None:
    juntos = unir_repetidos(
        [
            objeto("xablau raro", tipo_canonico="outro"),
            objeto("coisa estranha", tipo_canonico="outro"),
            objeto("Xablau Raros"),  # o plural do mesmo nome junta
        ]
    )
    assert [i.nome for i in juntos] == ["xablau raro", "coisa estranha"]
    assert len(juntos[0].caixas) == 2
