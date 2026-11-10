from typing import Any

from api.consolidacao import consolidar
from api.decupagem import Decupagem, Video
from api.janelas import Janela

DURACAO = 900_000
VIDEO = Video(sha256="a" * 64, duracao_ms=DURACAO)


def janela(indice: int, inicio: int, fim: int) -> Janela:
    return Janela(
        indice, inicio, fim, max(inicio - 30_000, 0), min(fim + 30_000, DURACAO)
    )


J0, J1, J2 = (
    janela(0, 0, 300_000),
    janela(1, 300_000, 600_000),
    janela(2, 600_000, 900_000),
)


def decupagem(**partes: Any) -> Decupagem:
    base: dict[str, Any] = {
        "versao_esquema": "1.5",
        "video": VIDEO.model_dump(),
        "programa": {"resumo": "", "blocos": []},
        "pautas": [],
        "pessoas": [],
        "planos": [],
        "comerciais": [],
        "transcricao": [],
    }
    return Decupagem.model_validate({**base, **partes})


def plano(id: str, inicio: int, fim: int) -> dict[str, Any]:
    return {
        "id": id,
        "inicio_ms": inicio,
        "fim_ms": fim,
        "ambiente": "estúdio",
        "plano_limpo": True,
    }


def pessoa(id: str, nome: str, imagem: list[tuple[int, int]]) -> dict[str, Any]:
    return {
        "id": id,
        "nome": nome,
        "na_imagem": [
            {"inicio_ms": i, "fim_ms": f, "evidencia": "rosto"} for i, f in imagem
        ],
        "citada_na_fala": [],
        "citada_no_texto": [],
    }


def comercial(
    marca: str, inicio: int, fim: int, tipo: str = "intervalo"
) -> dict[str, Any]:
    return {
        "marca": marca,
        "tipo": tipo,
        "evidencias": ["logo"],
        "inicio_ms": inicio,
        "fim_ms": fim,
    }


def pauta(
    id: str, inicio: int, fim: int, titulo: str, pessoas: list[str]
) -> dict[str, Any]:
    return {
        "id": id,
        "inicio_ms": inicio,
        "fim_ms": fim,
        "titulo": titulo,
        "resumo": f"resumo {titulo}",
        "pessoas": pessoas,
        "locais": [titulo],
    }


def test_item_no_contexto_compartilhado_sai_uma_vez_so() -> None:
    # 290–310 s: começa no núcleo da janela 0, e a janela 1 o vê no contexto.
    r0 = decupagem(planos=[plano("p1", 290_000, 310_000)])
    r1 = decupagem(
        planos=[plano("p1", 290_000, 310_000), plano("p2", 310_000, 320_000)]
    )

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [(p.id, p.inicio_ms, p.fim_ms) for p in d.planos] == [
        ("pla001", 290_000, 310_000),
        ("pla002", 310_000, 320_000),
    ]


def test_aparicao_e_comercial_que_atravessam_a_borda_sao_emendados() -> None:
    r0 = decupagem(
        pessoas=[pessoa("a", "Ana", [(290_000, 330_000)])],
        comerciais=[comercial("Marca X", 295_000, 330_000)],
    )
    r1 = decupagem(
        pessoas=[pessoa("b", "ana", [(290_000, 340_000)])],
        comerciais=[comercial("marca x", 295_000, 345_000)],
    )

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [(a.inicio_ms, a.fim_ms) for a in d.pessoas[0].na_imagem] == [
        (290_000, 340_000)
    ]
    assert [(c.inicio_ms, c.fim_ms) for c in d.comerciais] == [(295_000, 345_000)]


def test_comercial_de_outro_tipo_nao_emenda() -> None:
    r0 = decupagem(comerciais=[comercial("X", 295_000, 330_000)])
    r1 = decupagem(comerciais=[comercial("X", 295_000, 345_000, "marca_incidental")])

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [(c.inicio_ms, c.fim_ms) for c in d.comerciais] == [(295_000, 330_000)]


def test_pauta_que_atravessa_tres_janelas_vira_uma_so() -> None:
    r0 = decupagem(
        pessoas=[pessoa("a", "Ana", [])],
        pautas=[pauta("x", 100_000, 330_000, "Curta", ["a"])],
    )
    r1 = decupagem(
        pessoas=[pessoa("b", "Ana", []), pessoa("c", "Bia", [])],
        pautas=[pauta("y", 270_000, 630_000, "Longa", ["b", "c"])],
    )
    r2 = decupagem(
        pessoas=[pessoa("a", "Caio", [])],
        pautas=[pauta("z", 570_000, 700_000, "Final", ["a"])],
    )

    d = consolidar(VIDEO, [(J0, r0), (J1, r1), (J2, r2)], [])

    assert [(p.id, p.inicio_ms, p.fim_ms) for p in d.pautas] == [
        ("pau01", 100_000, 700_000)
    ]
    assert d.pautas[0].titulo == "Longa"
    assert d.pautas[0].resumo == "resumo Longa"
    assert d.pautas[0].locais == ["Curta", "Longa", "Final"]
    assert d.pautas[0].pessoas == ["pes01", "pes02", "pes03"]
    assert [p.nome for p in d.pessoas] == ["Ana", "Bia", "Caio"]


def test_blocos_que_se_sobrepoem_viram_um() -> None:
    def bloco(inicio: int, fim: int, titulo: str) -> dict[str, Any]:
        return {"inicio_ms": inicio, "fim_ms": fim, "titulo": titulo}

    r0 = decupagem(programa={"resumo": "um", "blocos": [bloco(0, 320_000, "Abertura")]})
    r1 = decupagem(
        programa={
            "resumo": "dois",
            "blocos": [
                bloco(290_000, 400_000, "Abertura"),
                bloco(500_000, 600_000, "B"),
            ],
        }
    )

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [(b.titulo, b.inicio_ms, b.fim_ms) for b in d.programa.blocos] == [
        ("Abertura", 0, 400_000),
        ("B", 500_000, 600_000),
    ]
    assert d.programa.resumo == "um dois"


def test_mesma_pessoa_vira_uma_so_e_nao_identificado_nao() -> None:
    r0 = decupagem(
        pessoas=[
            pessoa("a", "Ana", [(0, 1000)]),
            pessoa("n", "não identificado", [(0, 5)]),
        ]
    )
    r1 = decupagem(
        pessoas=[
            pessoa("a", "Ana", [(400_000, 401_000)]),
            pessoa("n", "não identificado", [(400_000, 400_005)]),
        ]
    )

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [(p.id, p.nome) for p in d.pessoas] == [
        ("pes01", "Ana"),
        ("pes02", "não identificado"),
        ("pes03", "não identificado"),
    ]
    assert len(d.pessoas[0].na_imagem) == 2


def test_video_de_uma_janela_sai_igual_a_entrada_menos_a_renumeracao() -> None:
    unica = janela(0, 0, DURACAO)
    r = decupagem(
        programa={"resumo": "tudo", "blocos": []},
        pautas=[pauta("zz", 0, DURACAO, "P", ["q"])],
        pessoas=[pessoa("q", "Ana", [(10, 20)])],
        planos=[plano("abc", 0, 500), plano("def", 500, DURACAO)],
        comerciais=[comercial("X", 1, 2)],
    )

    d = consolidar(VIDEO, [(unica, r)], [])

    esperado = r.model_dump()
    esperado["pautas"][0].update(id="pau01", pessoas=["pes01"])
    esperado["pessoas"][0]["id"] = "pes01"
    esperado["planos"][0]["id"] = "pla001"
    esperado["planos"][1]["id"] = "pla002"
    assert d.model_dump() == esperado


def test_regra_de_tempos_e_aplicada_no_fim() -> None:
    r = decupagem(planos=[plano("p", 1000, 9000)])

    d = consolidar(VIDEO, [(janela(0, 0, DURACAO), r)], [1200, 8800])

    # Os planos são os intervalos entre cortes que o plano do modelo cobre pela metade
    # ou mais; o herdado guarda os tempos do modelo.
    assert [(p.inicio_ms, p.fim_ms) for p in d.planos] == [(1200, 8800)]
    assert (d.planos[0].inicio_modelo_ms, d.planos[0].fim_modelo_ms) == (1000, 9000)


def test_emenda_nao_duplica_o_item_que_a_janela_seguinte_mantem() -> None:
    # 302–340 s começa no núcleo da janela 1: é outro item, não o par do 295–310.
    r0 = decupagem(
        pessoas=[pessoa("a", "Ana", [(295_000, 310_000)])],
        comerciais=[comercial("X", 295_000, 310_000)],
    )
    r1 = decupagem(
        pessoas=[pessoa("a", "Ana", [(302_000, 340_000)])],
        comerciais=[comercial("X", 302_000, 340_000)],
    )

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [(a.inicio_ms, a.fim_ms) for a in d.pessoas[0].na_imagem] == [
        (295_000, 310_000),
        (302_000, 340_000),
    ]
    assert [(c.inicio_ms, c.fim_ms) for c in d.comerciais] == [
        (295_000, 310_000),
        (302_000, 340_000),
    ]


def test_pauta_sobreposta_a_duas_da_janela_seguinte_vira_uma_so() -> None:
    r0 = decupagem(pautas=[pauta("a", 100_000, 310_000, "A", [])])
    r1 = decupagem(
        pautas=[
            pauta("b", 295_000, 305_000, "B", []),
            pauta("c", 305_000, 400_000, "C", []),
        ]
    )

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [(p.inicio_ms, p.fim_ms, p.titulo) for p in d.pautas] == [
        (100_000, 400_000, "A")
    ]


def test_duas_pautas_sobrepostas_a_uma_da_janela_seguinte_viram_uma_so() -> None:
    r0 = decupagem(
        pautas=[
            pauta("a", 100_000, 295_000, "A", []),
            pauta("b", 295_000, 310_000, "B", []),
        ]
    )
    r1 = decupagem(pautas=[pauta("c", 290_000, 400_000, "C", [])])

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [(p.inicio_ms, p.fim_ms) for p in d.pautas] == [(100_000, 400_000)]


def test_pessoa_so_com_itens_descartados_some() -> None:
    r0 = decupagem(pessoas=[pessoa("n", "não identificado", [(295_000, 305_000)])])
    r1 = decupagem(
        pessoas=[
            pessoa("n", "não identificado", [(295_000, 305_000)]),
            pessoa("a", "Ana", [(400_000, 401_000)]),
        ]
    )

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [(p.id, p.nome, len(p.na_imagem)) for p in d.pessoas] == [
        ("pes01", "não identificado", 1),
        ("pes02", "Ana", 1),
    ]


def test_regra_de_tempos_vem_depois_da_emenda() -> None:
    r0 = decupagem(pessoas=[pessoa("a", "Ana", [(295_000, 310_000)])])
    r1 = decupagem(pessoas=[pessoa("a", "Ana", [(295_000, 339_500)])])

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [340_000])

    a = d.pessoas[0].na_imagem[0]
    assert (a.inicio_ms, a.fim_ms, a.fim_modelo_ms) == (295_000, 340_000, 339_500)


def test_texto_na_tela_fica_com_a_janela_em_cujo_nucleo_comeca() -> None:
    def gc(inicio: int, fim: int) -> dict[str, Any]:
        return {"inicio_ms": inicio, "fim_ms": fim, "tipo": "gc", "texto": "FULANA"}

    r0 = decupagem(textos_na_tela=[gc(290_000, 295_000)])
    r1 = decupagem(textos_na_tela=[gc(290_000, 295_000), gc(305_000, 306_000)])

    d = consolidar(VIDEO, [(J0, r0), (J1, r1)], [])

    assert [(t.inicio_ms, t.fim_ms) for t in d.textos_na_tela] == [
        (290_000, 295_000),
        (305_000, 306_000),
    ]
