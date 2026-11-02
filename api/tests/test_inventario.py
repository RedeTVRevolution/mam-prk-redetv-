"""Conversão do resultado do Florence-2 e motor Gemini para o inventário (#244)."""

import json
from typing import Any

import pytest

from api.decupagem import Decupagem, Plano
from api.florence import (
    ObjetoDetectado,
    ObjetosDaDecupagem,
    QuadroDetectado,
    RegiaoLegendada,
)
from api.gemini import AnaliseFalhou
from api.inventario import (
    aplicar_inventario,
    converter_do_florence,
    olhar_com_gemini,
)
from api.leitura_da_tela import Caixa
from api.tests.test_decupagem import decupagem_valida
from api.tests.test_gemini import TransporteFalso
from api.versao_pipeline import VERSAO_PIPELINE, manifesto


def plano(indice: int, quadros: list[str]) -> Plano:
    return Plano(
        id=f"pla{indice:02d}",
        inicio_ms=indice * 1000,
        fim_ms=indice * 1000 + 900,
        ambiente="sala",
        plano_limpo=True,
        quadros=quadros,
    )


def decupagem(*quadros_por_plano: list[str]) -> Decupagem:
    base = Decupagem.model_validate(decupagem_valida())
    return base.model_copy(
        update={"planos": [plano(i, q) for i, q in enumerate(quadros_por_plano)]}
    )


def caixa(x: float = 0.25, y: float = 0.25, l: float = 0.5, a: float = 0.5) -> Caixa:
    return Caixa(x=x, y=y, largura=l, altura=a)


def quadro(plano_: int, caminho: str, **achados: Any) -> QuadroDetectado:
    return QuadroDetectado(
        plano=plano_,
        caminho=caminho,
        largura=1920,
        altura=1080,
        objetos=achados.get("objetos", []),
        regioes=achados.get("regioes", []),
    )


def bruto(*quadros: QuadroDetectado) -> ObjetosDaDecupagem:
    return ObjetosDaDecupagem(modelo="florence@x", quadros=list(quadros))


def resposta(*planos: dict[str, Any]) -> str:
    return json.dumps({"planos": list(planos)})


def convertido(nome: str, deteccoes: list[str], **mais: Any) -> dict[str, Any]:
    return {
        "nome": nome,
        "categoria": "movel",
        "cor": None,
        "marca": None,
        "deteccoes": deteccoes,
        **mais,
    }


COM_SOFA = bruto(
    quadro(
        0,
        "q/a.jpg",
        objetos=[ObjetoDetectado(rotulo="couch", caixa=caixa())],
        regioes=[
            RegiaoLegendada(legenda="a gray sofa", caixa=caixa(0.2, 0.2, 0.6, 0.6))
        ],
    )
)


def test_a_conversao_e_uma_chamada_so_de_texto_sem_imagem() -> None:
    transporte = TransporteFalso(
        resposta({"plano": 0, "objetos": [convertido("sofá", ["p0q0o0"], cor="cinza")]})
    )

    converter_do_florence(
        decupagem(["q/a.jpg"]), COM_SOFA, transporte=transporte, modelo="m", job_id="j1"
    )

    (chamada,) = transporte.chamadas
    assert chamada.imagens == ()
    assert chamada.video_uri == ""
    assert chamada.modelo == "m"
    assert chamada.rotulos["etapa"] == "inventario_de_objetos"
    assert chamada.rotulos["job_id"] == "j1"
    assert "couch" in chamada.instrucao + chamada.texto
    assert "português" in chamada.instrucao


def test_o_inventario_traz_nome_categoria_cor_marca_caixas_e_destaque() -> None:
    transporte = TransporteFalso(
        resposta(
            {
                "plano": 0,
                "objetos": [
                    convertido("sofá", ["p0q0o0"], cor="cinza", marca="Tok&Stok")
                ],
            }
        )
    )

    inventarios = converter_do_florence(
        decupagem(["q/a.jpg"]), COM_SOFA, transporte=transporte, modelo="m", job_id="j1"
    )

    (sofa,) = inventarios[0]
    assert (sofa.nome, sofa.categoria, sofa.cor, sofa.marca) == (
        "sofá",
        "movel",
        "cinza",
        "Tok&Stok",
    )
    assert sofa.caixas[0].quadro == "q/a.jpg"
    assert (sofa.caixas[0].x, sofa.caixas[0].largura) == (0.25, 0.5)
    assert sofa.destaque == 3  # grande e no centro


def test_a_caixa_vem_da_deteccao_e_nao_do_modelo() -> None:
    transporte = TransporteFalso(
        resposta(
            {"plano": 0, "objetos": [convertido("tapete", ["p0q0r0", "inventado"])]}
        )
    )

    inventarios = converter_do_florence(
        decupagem(["q/a.jpg"]), COM_SOFA, transporte=transporte, modelo="m", job_id="j1"
    )

    (item,) = inventarios[0]
    assert [c.largura for c in item.caixas] == [0.6]  # a da região; o id inventado cai


def test_objeto_sem_nenhuma_deteccao_valida_e_descartado() -> None:
    transporte = TransporteFalso(
        resposta({"plano": 0, "objetos": [convertido("fantasma", ["nada"])]})
    )

    inventarios = converter_do_florence(
        decupagem(["q/a.jpg"]), COM_SOFA, transporte=transporte, modelo="m", job_id="j1"
    )

    assert inventarios[0] == []


def test_o_mesmo_objeto_nos_quadros_do_plano_vira_um_com_as_caixas_e_o_maior_destaque() -> (
    None
):
    dois = bruto(
        quadro(
            0,
            "q/a.jpg",
            objetos=[ObjetoDetectado(rotulo="couch", caixa=caixa(0.0, 0.0, 0.1, 0.1))],
        ),
        quadro(0, "q/b.jpg", objetos=[ObjetoDetectado(rotulo="couch", caixa=caixa())]),
    )
    transporte = TransporteFalso(
        resposta(
            {
                "plano": 0,
                "objetos": [
                    convertido("Sofá", ["p0q0o0"], cor="cinza"),
                    convertido("sofa", ["p0q1o0"], cor="cinza"),
                ],
            }
        )
    )

    inventarios = converter_do_florence(
        decupagem(["q/a.jpg", "q/b.jpg"]),
        dois,
        transporte=transporte,
        modelo="m",
        job_id="j1",
    )

    (sofa,) = inventarios[0]
    assert [c.quadro for c in sofa.caixas] == ["q/a.jpg", "q/b.jpg"]
    assert sofa.destaque == 3


def test_cor_diferente_nao_une_os_objetos() -> None:
    transporte = TransporteFalso(
        resposta(
            {
                "plano": 0,
                "objetos": [
                    convertido("sofá", ["p0q0o0"], cor="cinza"),
                    convertido("sofá", ["p0q0r0"], cor="azul"),
                ],
            }
        )
    )

    inventarios = converter_do_florence(
        decupagem(["q/a.jpg"]), COM_SOFA, transporte=transporte, modelo="m", job_id="j1"
    )

    assert [i.cor for i in inventarios[0]] == ["cinza", "azul"]


def test_planos_em_lotes_uma_chamada_por_lote() -> None:
    planos = [[f"q/{i}.jpg"] for i in range(5)]
    quadros = bruto(
        *[
            quadro(
                i,
                f"q/{i}.jpg",
                objetos=[ObjetoDetectado(rotulo="vase", caixa=caixa())],
            )
            for i in range(5)
        ]
    )
    transporte = TransporteFalso(
        resposta(
            *[
                {"plano": i, "objetos": [convertido("vaso", [f"p{i}q0o0"])]}
                for i in range(2)
            ]
        ),
        resposta(
            *[
                {"plano": i, "objetos": [convertido("vaso", [f"p{i}q0o0"])]}
                for i in range(2, 4)
            ]
        ),
        resposta({"plano": 4, "objetos": [convertido("vaso", ["p4q0o0"])]}),
    )

    inventarios = converter_do_florence(
        decupagem(*planos),
        quadros,
        transporte=transporte,
        modelo="m",
        job_id="j1",
        planos_por_lote=2,
    )

    assert len(transporte.chamadas) == 3
    assert sorted(inventarios) == [0, 1, 2, 3, 4]
    assert "p4q0o0" in transporte.chamadas[2].instrucao + transporte.chamadas[2].texto
    assert (
        "p0q0o0" not in transporte.chamadas[2].instrucao + transporte.chamadas[2].texto
    )


def test_resposta_fora_do_esquema_esgota_e_levanta() -> None:
    transporte = TransporteFalso(*(["isto não é json"] * 10))

    with pytest.raises(AnaliseFalhou):
        converter_do_florence(
            decupagem(["q/a.jpg"]),
            COM_SOFA,
            transporte=transporte,
            modelo="m",
            job_id="j1",
            dormir=lambda s: None,
        )


def test_a_legenda_em_ingles_nao_vai_para_a_decupagem() -> None:
    transporte = TransporteFalso(
        resposta({"plano": 0, "objetos": [convertido("sofá", ["p0q0o0", "p0q0r0"])]})
    )
    d = decupagem(["q/a.jpg"])

    inventarios = converter_do_florence(
        d, COM_SOFA, transporte=transporte, modelo="m", job_id="j1"
    )
    nova = aplicar_inventario(d, inventarios, motor="florence", modelo="m")

    texto = nova.model_dump_json()
    assert "couch" not in texto
    assert "gray sofa" not in texto
    assert nova.planos[0].inventario[0].nome == "sofá"
    assert nova.inventario_gerado_por is not None
    assert nova.inventario_gerado_por.model_dump() == {
        "motor": "florence",
        "modelo": "m",
    }


def test_aplicar_substitui_o_inventario_anterior() -> None:
    d = decupagem(["q/a.jpg"])
    transporte = TransporteFalso(
        resposta({"plano": 0, "objetos": [convertido("sofá", ["p0q0o0"])]})
    )
    inventarios = converter_do_florence(
        d, COM_SOFA, transporte=transporte, modelo="m", job_id="j1"
    )

    uma = aplicar_inventario(d, inventarios, motor="florence", modelo="m")
    duas = aplicar_inventario(uma, inventarios, motor="florence", modelo="m")

    assert len(duas.planos[0].inventario) == 1


def test_o_manifesto_do_pipeline_leva_o_motor_que_rodou() -> None:
    d = decupagem(["q/a.jpg"]).model_copy(
        update={
            "versao_pipeline": VERSAO_PIPELINE,
            "manifesto_do_pipeline": manifesto(),
        }
    )

    nova = aplicar_inventario(d, {}, motor="gemini", modelo="gemini-x")

    assert nova.manifesto_do_pipeline is not None
    objetos = nova.manifesto_do_pipeline["motores"]["objetos"]
    assert (objetos["motor"], objetos["modelo"]) == ("gemini", "gemini-x")
    assert d.manifesto_do_pipeline == manifesto()  # a de antes não muda


def test_sem_manifesto_o_inventario_nao_inventa_um() -> None:
    nova = aplicar_inventario(decupagem(["q/a.jpg"]), {}, motor="florence", modelo="m")

    assert nova.manifesto_do_pipeline is None


def visto(nome: str, quadro_: int, **caixa_: float) -> dict[str, Any]:
    return {
        "nome": nome,
        "categoria": "decoracao",
        "cor": "dourado",
        "marca": None,
        "caixas": [
            {"quadro": quadro_, "x": 0.4, "y": 0.4, "largura": 0.2, "altura": 0.2}
            | caixa_
        ],
    }


def test_motor_gemini_manda_os_quadros_com_o_modelo_da_configuracao() -> None:
    d = decupagem(["q/a.jpg", "q/b.jpg"])
    transporte = TransporteFalso(
        resposta({"plano": 0, "objetos": [visto("quadro na parede", 1)]})
    )
    pedidos: list[str] = []

    def jpeg(caminho: str) -> bytes:
        pedidos.append(caminho)
        return caminho.encode()

    inventarios = olhar_com_gemini(
        d, transporte=transporte, modelo="gemini-3.8-flash", job_id="j1", quadro_de=jpeg
    )

    (chamada,) = transporte.chamadas
    assert chamada.modelo == "gemini-3.8-flash"
    assert chamada.imagens == (b"q/a.jpg", b"q/b.jpg")
    assert chamada.rotulos["etapa"] == "inventario_de_objetos"
    (item,) = inventarios[0]
    assert item.nome == "quadro na parede"
    assert item.caixas[0].quadro == "q/b.jpg"
    assert item.destaque == 2  # área 4%, no centro


def test_motor_gemini_ignora_caixa_de_quadro_que_nao_existe() -> None:
    d = decupagem(["q/a.jpg"])
    transporte = TransporteFalso(resposta({"plano": 0, "objetos": [visto("vaso", 7)]}))

    inventarios = olhar_com_gemini(
        d, transporte=transporte, modelo="m", job_id="j1", quadro_de=lambda c: b"x"
    )

    assert inventarios[0] == []


def test_plano_sem_quadros_nao_gera_chamada() -> None:
    transporte = TransporteFalso()

    inventarios = olhar_com_gemini(
        decupagem([]),
        transporte=transporte,
        modelo="m",
        job_id="j1",
        quadro_de=lambda c: b"x",
    )

    assert inventarios == {0: []}
    assert transporte.chamadas == []
