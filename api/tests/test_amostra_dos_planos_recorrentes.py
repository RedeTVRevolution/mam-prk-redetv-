"""A amostragem dos planos recorrentes (#546), ferramenta em `api/ferramentas/`."""

import json
from pathlib import Path

import pytest

from api.ferramentas.amostra_dos_planos_recorrentes import (
    PlanoDaAmostra,
    amostra_de_cobertura,
    amostra_de_precisao,
    main,
    resumo,
)
from api.planos_recorrentes import Sinal, com_os_planos_recorrentes
from api.tests.test_planos_recorrentes import _QUADROS, _decupagem, _plano


def test_a_pasta_local_mostra_o_numero_de_grupos_e_os_maiores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pasta = tmp_path / "v1"
    (pasta / "quadros").mkdir(parents=True)
    nomes = ["a1", "b1", "a2", "b2", "a1", "c1"]
    planos = [_plano(f"p{n}", n, f"quadros/{q}.png") for n, q in enumerate(nomes)]
    (pasta / "decupagem.json").write_text(_decupagem(planos).model_dump_json())
    for nome in set(nomes):
        (pasta / f"quadros/{nome}.png").write_bytes(_QUADROS[nome])

    assert main([str(pasta)]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "v1: 6 planos, 5 em 2 grupos",
        "  rec01: 3 planos, 0.1 min",
        "  rec02: 2 planos, 0.0 min",
    ]
    pronta = com_os_planos_recorrentes(
        _decupagem(planos), lambda c: _QUADROS[Path(c).stem]
    )
    assert resumo(pronta, quantos=1) == [("rec01", 3, 3000)]
    assert main([]) == 2


def _p(
    programa: str, video: str, plano: str, grupo: str | None, bits: int
) -> PlanoDaAmostra:
    return PlanoDaAmostra(programa, video, plano, grupo, Sinal((1 << bits) - 1, (1.0,)))


def test_a_precisao_sorteia_um_par_por_grupo_estavel_e_por_programa() -> None:
    planos = [
        *(_p("jornal", "v1", f"a{i}", "rec01", 0) for i in range(4)),
        *(_p("jornal", "v1", f"b{i}", "rec02", 0) for i in range(2)),
        *(_p("novela", "v2", f"c{i}", "rec01", 0) for i in range(3)),
        _p("novela", "v2", "solto", None, 0),
    ]

    amostra = amostra_de_precisao(planos, 10)

    assert sorted((a["programa"], a["video"], a["grupo"]) for a in amostra) == [
        ("jornal", "v1", "rec01"),
        ("jornal", "v1", "rec02"),
        ("novela", "v2", "rec01"),
    ]
    assert all(a["plano_a"] != a["plano_b"] for a in amostra)
    assert {a["programa"] for a in amostra[:2]} == {"jornal", "novela"}
    assert amostra == amostra_de_precisao(list(reversed(planos)), 10)
    assert len(amostra_de_precisao(planos, 2)) == 2


def test_a_cobertura_pareia_o_vizinho_mais_proximo_de_outro_grupo_no_mesmo_video() -> (
    None
):
    planos = [
        _p("jornal", "v1", "a", "rec01", 0),
        _p("jornal", "v1", "b", "rec01", 0),
        _p("jornal", "v1", "c", None, 2),  # solto, perto do rec01
        _p("jornal", "v1", "d", "rec02", 40),  # longe
        _p("jornal", "v2", "e", None, 1),  # outro vídeo: não se mistura
    ]

    amostra = amostra_de_cobertura(planos, 10)

    assert all(a["video"] == "v1" and a["programa"] == "jornal" for a in amostra)
    pares = {frozenset((a["plano_a"], a["plano_b"])) for a in amostra}
    assert frozenset({"a", "c"}) in pares
    assert all(frozenset(p) not in pares for p in (("a", "b"), ("a", "e"), ("c", "e")))


def test_a_pasta_local_imprime_as_amostras_em_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pasta = tmp_path / "jornal" / "v1"
    (pasta / "quadros").mkdir(parents=True)
    nomes = ["a1", "b1", "a2", "b2", "a1", "c1"]
    planos = [_plano(f"p{n}", n, f"quadros/{q}.png") for n, q in enumerate(nomes)]
    (pasta / "decupagem.json").write_text(_decupagem(planos).model_dump_json())
    for nome in set(nomes):
        (pasta / f"quadros/{nome}.png").write_bytes(_QUADROS[nome])

    assert main(["--amostra=5", str(pasta)]) == 0

    saida = json.loads(capsys.readouterr().out)
    assert {p["programa"] for p in saida["amostra_de_precisao"]} == {"jornal"}
    assert len(saida["amostra_de_precisao"]) == 2  # rec01 e rec02, um par cada
    assert saida["amostra_de_cobertura"]
    assert saida["margem_da_precisao_com_100_pares_pontos"] == 4.3
