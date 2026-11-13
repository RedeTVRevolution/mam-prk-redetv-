import ast
import sys
from pathlib import Path

import pytest

from api.ambiente import FaltaNoAmbiente, exigir_do_ambiente


def test_devolve_o_valor_presente() -> None:
    assert exigir_do_ambiente({"A": "x"}, "A") == "x"


@pytest.mark.parametrize("ambiente", [{}, {"A": ""}])
def test_ausente_ou_vazia_e_falta_no_ambiente(ambiente: dict[str, str]) -> None:
    with pytest.raises(FaltaNoAmbiente, match="A não está no ambiente"):
        exigir_do_ambiente(ambiente, "A")


def test_o_modulo_importa_so_a_biblioteca_padrao() -> None:
    arvore = ast.parse((Path(__file__).parents[1] / "ambiente.py").read_text())
    raizes = {
        (n.module or "").split(".")[0]
        if isinstance(n, ast.ImportFrom)
        else a.name.split(".")[0]
        for n in ast.walk(arvore)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert raizes <= sys.stdlib_module_names
