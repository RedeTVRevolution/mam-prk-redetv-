"""Os sorteios por hash que as ferramentas fazem hoje (#658): os valores estão gravados aqui
e não mudam. O conjunto reservado da regressão e as amostras "iguais antes e depois" dependem
disso; trocar o hash de lugar não pode mexer em nenhum."""

from api.ferramentas.amostra_dos_planos_recorrentes import (
    PlanoDaAmostra,
)
from api.ferramentas.amostra_dos_planos_recorrentes import (
    amostra_de_precisao as precisao_dos_planos,
)
from api.medir_agrupamento_de_objetos import amostra_de_cobertura, amostra_de_precisao
from api.medir_juncao import amostra as amostra_da_juncao
from api.planos_recorrentes import Sinal
from api.regressao import reservado_pelo_sorteio
from api.tests.test_juncao_de_pessoas import decupagem, pessoa


def test_ids_reservados_pela_regressao() -> None:
    reservados = [n for n in range(60) if reservado_pelo_sorteio(f"caso-{n:02d}")]

    assert reservados == [9, 11, 26, 29, 31, 33, 38, 40, 41]


def test_pares_da_precisao_do_agrupamento_de_objetos() -> None:
    grupos = {
        p: {f"g{i}": {f"Nome {i}a", f"Nome {i}b", f"Nome {i}c"} for i in range(5)}
        for p in ("jornal", "novela")
    }

    pares = amostra_de_precisao(grupos, 7)

    assert [(p["programa"], p["grupo"], p["a"], p["b"]) for p in pares] == [
        ("jornal", "g3", "Nome 3a", "Nome 3b"),
        ("novela", "g3", "Nome 3a", "Nome 3b"),
        ("jornal", "g2", "Nome 2a", "Nome 2b"),
        ("novela", "g2", "Nome 2a", "Nome 2b"),
        ("jornal", "g1", "Nome 1a", "Nome 1b"),
        ("novela", "g1", "Nome 1a", "Nome 1b"),
        ("jornal", "g4", "Nome 4a", "Nome 4b"),
    ]


def test_pares_da_cobertura_do_agrupamento_de_objetos() -> None:
    grupos = {
        "jornal": {
            "c1": {"mesa de vidro", "mesa de madeira"},
            "c2": {"mesa grande", "cadeira de vidro"},
            "c3": {"cadeira de madeira"},
        }
    }

    pares = amostra_de_cobertura(grupos, 20)

    assert [(p["palavra"], p["a"], p["b"]) for p in pares] == [
        ("cadeira", "cadeira de madeira", "cadeira de vidro"),
        ("madeira", "cadeira de madeira", "mesa de madeira"),
        ("mesa", "mesa de vidro", "mesa grande"),
        ("mesa", "mesa de madeira", "mesa grande"),
        ("vidro", "cadeira de vidro", "mesa de vidro"),
    ]


def test_pares_da_precisao_dos_planos_recorrentes() -> None:
    planos = [
        PlanoDaAmostra(p, v, f"x{i}", f"rec{k}", Sinal(1 << 0, (1.0,)))
        for p, v in (("jornal", "v1"), ("novela", "v2"))
        for k in range(3)
        for i in range(3)
    ]

    pares = precisao_dos_planos(planos, 7)

    assert [(p["programa"], p["grupo"], p["plano_a"], p["plano_b"]) for p in pares] == [
        ("jornal", "rec0", "x1", "x2"),
        ("novela", "rec0", "x2", "x1"),
        ("jornal", "rec2", "x1", "x2"),
        ("novela", "rec1", "x2", "x1"),
        ("jornal", "rec1", "x1", "x2"),
        ("novela", "rec2", "x2", "x1"),
    ]


def test_grupos_da_juncao() -> None:
    pessoas = []
    for i in range(5):
        for janela, base in ((0, 100_000), (1, 400_000), (2, 700_000)):
            pessoas.append(
                pessoa(
                    f"p{'abc'[janela]}{i}",
                    janela,
                    [(base + i * 1000, base + 500 + i * 1000)],
                    nome=f"Não identificado, camisa {i}",
                )
            )
    d = decupagem(pessoas)

    a = amostra_da_juncao({"a.json": d, "b.json": d}, 6)

    assert [(p["grupo"], p["a"], p["b"]) for p in a] == [
        (
            "b.json:pa0",
            "nao identificado, camisa 4@104000-104500",
            "nao identificado, camisa 4@404000-404500",
        ),
        (
            "a.json:pa0",
            "nao identificado, camisa 0@700000-700500",
            "nao identificado, camisa 1@101000-101500",
        ),
    ]
