"""Objetos por tipo canônico (#544): esquema, conversão e junção no plano."""

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from api.decupagem import (
    CaixaDoQuadro,
    Decupagem,
    ObjetoDoInventario,
    esquema_do_modelo,
)
from api.inventario import (
    RespostaConvertida,
    RespostaVista,
    _esquema,
    converter_do_florence,
    unir_repetidos,
)
from api.taxonomia_de_objetos import OPCOES_DE_TIPO
from api.tests.test_decupagem import decupagem_valida
from api.tests.test_gemini import TransporteFalso
from api.tests.test_inventario import (
    COM_SOFA,
    convertido,
    decupagem,
    resposta,
)


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


def test_unir_repetidos_junta_pela_assinatura_do_nome_e_nao_pelo_tipo() -> None:
    juntos = unir_repetidos(
        [
            objeto("camiseta", tipo_canonico="camisa"),
            objeto(
                "camisetas", tipo_canonico="camisa", caixas=[caixa(0.5)], destaque=3
            ),
            objeto("blusa", tipo_canonico="camisa"),  # outro nome bruto: fica
            objeto("camisa listrada", tipo_canonico="camisa"),
            objeto("camisa estampada", tipo_canonico="camisa"),
        ]
    )
    assert [i.nome for i in juntos] == [
        "camiseta",
        "blusa",
        "camisa listrada",
        "camisa estampada",
    ]
    assert len(juntos[0].caixas) == 2
    assert juntos[0].destaque == 3


def test_mesmo_nome_com_cor_ou_marca_diferente_mantem_cada_combinacao() -> None:
    juntos = unir_repetidos(
        [
            objeto("camisa", tipo_canonico="camisa", cor="azul", marca="Nike"),
            objeto("camisa", tipo_canonico="camisa", cor="branco", marca="Nike"),
            objeto("camisa", tipo_canonico="camisa", cor="azul", marca="Adidas"),
            objeto("camisa", tipo_canonico="camisa", cor="azul", marca=None),
        ]
    )
    assert [(i.cor, i.marca, len(i.caixas)) for i in juntos] == [
        ("azul", "Nike", 2),  # a sem marca entra na que tem
        ("branco", "Nike", 1),
        ("azul", "Adidas", 1),
    ]


def test_mesmo_nome_em_categorias_diferentes_continua_separado() -> None:
    juntos = unir_repetidos(
        [objeto("vaso", categoria="decoracao"), objeto("vaso", categoria="movel")]
    )
    assert len(juntos) == 2


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


NOMES = [
    ("camisa", "camisa"),
    ("blusa", "camisa"),
    ("camiseta", None),
    ("xablau raro", "outro"),
    ("Xablau Raros", None),
    ("coisa estranha", "outro"),
]


@st.composite
def _itens(draw: st.DrawFn) -> list[ObjetoDoInventario]:
    itens = []
    for _ in range(draw(st.integers(0, 8))):
        nome, tipo = draw(st.sampled_from(NOMES))
        extra: dict[str, Any] = {
            "cor": draw(st.sampled_from([None, "azul", "branco"])),
            "marca": draw(st.sampled_from([None, "Nike", "Adidas"])),
            "destaque": draw(st.integers(1, 3)),
            "caixas": [
                caixa(draw(st.floats(0, 0.5))) for _ in range(draw(st.integers(1, 3)))
            ],
        }
        if tipo:
            extra["tipo_canonico"] = tipo
        itens.append(objeto(nome, **extra))
    return itens


@given(_itens())
def test_juntar_conserva_as_caixas_e_o_maior_destaque(
    itens: list[ObjetoDoInventario],
) -> None:
    juntos = unir_repetidos(itens)

    assert sum(len(i.caixas) for i in juntos) == sum(len(i.caixas) for i in itens)
    assert max((i.destaque for i in juntos), default=0) == max(
        (i.destaque for i in itens), default=0
    )
    assert len(juntos) <= len(itens)


@given(_itens())
def test_juntar_o_que_ja_foi_juntado_nao_muda_nada(
    itens: list[ObjetoDoInventario],
) -> None:
    uma_vez = unir_repetidos(itens)

    assert unir_repetidos(uma_vez) == uma_vez
