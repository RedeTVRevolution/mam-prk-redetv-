"""O "dia" e o "agora" de São Paulo vivem em `api/fuso.py` (#636)."""

import ast
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from api import fuso

RAIZ = Path(__file__).parents[1]


def test_virada_do_dia() -> None:
    # 02h59 UTC ainda é o dia 14 em São Paulo; às 03h00 UTC vira o dia 15.
    antes = datetime(2026, 11, 15, 2, 59, tzinfo=UTC)
    depois = datetime(2026, 11, 15, 3, 0, tzinfo=UTC)

    assert antes.astimezone(fuso.SAO_PAULO).date() == date(2026, 11, 14)
    assert depois.astimezone(fuso.SAO_PAULO).date() == date(2026, 11, 15)


def test_23h30_de_sao_paulo_e_o_dia_seguinte_em_utc() -> None:
    noite = datetime(2026, 11, 14, 23, 30, tzinfo=fuso.SAO_PAULO)

    assert noite.astimezone(UTC).date() == date(2026, 11, 15)
    assert noite.date() == date(2026, 11, 14)


def test_agora_em_sao_paulo_e_o_instante_atual_no_fuso() -> None:
    assert fuso.agora_em_sao_paulo().tzinfo == fuso.SAO_PAULO


def test_periodo_em_utc_com_as_duas_pontas() -> None:
    inicio, fim = fuso.periodo_em_utc(date(2026, 11, 13), date(2026, 11, 14))

    assert inicio == datetime(2026, 11, 13, 3, 0, tzinfo=UTC)
    assert fim == datetime(2026, 11, 15, 3, 0, tzinfo=UTC)  # exclusivo


def test_periodo_em_utc_com_uma_ponta_so() -> None:
    assert fuso.periodo_em_utc(date(2026, 11, 13), None) == (
        datetime(2026, 11, 13, 3, 0, tzinfo=UTC),
        None,
    )
    assert fuso.periodo_em_utc(None, date(2026, 11, 13)) == (
        None,
        datetime(2026, 11, 14, 3, 0, tzinfo=UTC),
    )


def test_periodo_em_utc_sem_pontas() -> None:
    assert fuso.periodo_em_utc(None, None) == (None, None)


def _importados(arquivo: Path) -> set[str]:
    nomes: set[str] = set()
    for no in ast.walk(ast.parse(arquivo.read_text())):
        if isinstance(no, ast.Import):
            nomes |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom):
            nomes.add((no.module or "").split(".")[0])
    return nomes


def test_fuso_so_importa_a_biblioteca_padrao() -> None:
    assert _importados(RAIZ / "fuso.py") <= sys.stdlib_module_names


def test_periodo_padrao_nao_arrasta_qualidade_do_painel_nem_firestore() -> None:
    texto = (RAIZ / "periodo_padrao.py").read_text()

    assert "qualidade_do_painel" not in texto
    assert "firestore" not in texto.lower()


def test_so_o_modulo_de_fuso_escreve_o_nome_do_fuso() -> None:
    escrevem = [
        str(p.relative_to(RAIZ))
        for p in RAIZ.rglob("*.py")
        if p != RAIZ / "fuso.py"
        and "tests" not in p.parts
        and "America/Sao_Paulo" in p.read_text()
    ]

    assert escrevem == [], "o nome do fuso só se escreve em api/fuso.py"
