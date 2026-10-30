from collections.abc import Sequence

from api.decupagem import Pessoa
from api.pessoas import tempo_de_tela_ms, unir_pessoas


def pessoa(
    id: str,
    nome: str,
    *,
    imagem: Sequence[tuple[int, int]] = (),
    fala: Sequence[tuple[int, int]] = (),
    texto: Sequence[tuple[int, int]] = (),
    origem: str = "modelo",
) -> Pessoa:
    return Pessoa.model_validate(
        {
            "id": id,
            "nome": nome,
            "origem": origem,
            "na_imagem": [
                {"inicio_ms": i, "fim_ms": f, "evidencia": "rosto"} for i, f in imagem
            ],
            "citada_na_fala": [{"inicio_ms": i, "fim_ms": f} for i, f in fala],
            "citada_no_texto": [
                {"inicio_ms": i, "fim_ms": f, "texto": "X"} for i, f in texto
            ],
        }
    )


def test_mesma_pessoa_em_duas_janelas_vira_uma_so() -> None:
    unidas, mapa = unir_pessoas(
        [
            [pessoa("a1", "José da Silva", imagem=[(0, 1000)])],
            [pessoa("b7", "jose  da silva", imagem=[(300_000, 301_000)])],
        ]
    )

    assert [p.id for p in unidas] == ["pes01"]
    assert unidas[0].nome == "José da Silva"
    assert [(a.inicio_ms, a.fim_ms) for a in unidas[0].na_imagem] == [
        (0, 1000),
        (300_000, 301_000),
    ]
    assert mapa == {0: {"a1": "pes01"}, 1: {"b7": "pes01"}}


def test_ids_novos_seguem_a_ordem_da_primeira_ocorrencia() -> None:
    unidas, mapa = unir_pessoas(
        [
            [pessoa("x", "Ana"), pessoa("y", "Bia")],
            [pessoa("x", "Carla"), pessoa("y", "Ana")],
        ]
    )

    assert [(p.id, p.nome) for p in unidas] == [
        ("pes01", "Ana"),
        ("pes02", "Bia"),
        ("pes03", "Carla"),
    ]
    assert mapa == {0: {"x": "pes01", "y": "pes02"}, 1: {"x": "pes03", "y": "pes01"}}


def test_nao_identificado_nunca_e_unido() -> None:
    unidas, mapa = unir_pessoas(
        [
            [pessoa("a", "não identificado")],
            [pessoa("a", "Não Identificado"), pessoa("b", "nao identificado")],
        ]
    )

    assert [p.id for p in unidas] == ["pes01", "pes02", "pes03"]
    assert mapa == {0: {"a": "pes01"}, 1: {"a": "pes02", "b": "pes03"}}


def test_mencao_numa_janela_e_imagem_em_outra_sem_promocao() -> None:
    unidas, _ = unir_pessoas(
        [
            [pessoa("a", "Ana", fala=[(5000, 6000)], texto=[(7000, 8000)])],
            [pessoa("a", "ana", imagem=[(400_000, 401_000)])],
        ]
    )

    (ana,) = unidas
    assert [(a.inicio_ms, a.fim_ms) for a in ana.na_imagem] == [(400_000, 401_000)]
    assert [(m.inicio_ms, m.fim_ms) for m in ana.citada_na_fala] == [(5000, 6000)]
    assert [(m.inicio_ms, m.fim_ms) for m in ana.citada_no_texto] == [(7000, 8000)]


def test_listas_unidas_em_ordem_de_inicio() -> None:
    unidas, _ = unir_pessoas(
        [
            [pessoa("a", "Ana", imagem=[(5000, 6000)])],
            [pessoa("a", "Ana", imagem=[(1000, 2000)])],
        ]
    )

    assert [a.inicio_ms for a in unidas[0].na_imagem] == [1000, 5000]


def test_origem_revisao_se_alguma_parte_veio_de_revisao() -> None:
    unidas, _ = unir_pessoas(
        [
            [pessoa("a", "Ana")],
            [pessoa("a", "Ana", origem="revisao")],
            [pessoa("a", "Ana")],
        ]
    )

    assert unidas[0].origem == "revisao"


def test_sem_janelas_nao_ha_pessoas() -> None:
    assert unir_pessoas([]) == ([], {})


def test_tempo_de_tela_junta_aparicoes_sobrepostas() -> None:
    ana = pessoa("a", "Ana", imagem=[(0, 4000), (3000, 6000), (10_000, 11_000)])

    assert tempo_de_tela_ms(ana) == 7000


def test_tempo_de_tela_ignora_aparicao_contida_e_desordenada() -> None:
    ana = pessoa("a", "Ana", imagem=[(5000, 6000), (0, 10_000)])

    assert tempo_de_tela_ms(ana) == 10_000


def test_tempo_de_tela_nao_conta_mencoes() -> None:
    ana = pessoa(
        "a", "Ana", imagem=[(0, 1000)], fala=[(2000, 9000)], texto=[(3000, 9000)]
    )

    assert tempo_de_tela_ms(ana) == 1000
    assert tempo_de_tela_ms(pessoa("b", "Bia", fala=[(0, 5000)])) == 0
