"""A única saída de CSV da aplicação: texto que começa como fórmula não vira fórmula (#461)."""

import csv
import io
from collections.abc import Sequence


def _celula(valor: object) -> object:
    """Texto que começa como fórmula não vira fórmula na planilha."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{valor}"
    return valor


def csv_em_texto(colunas: Sequence[str], linhas: Sequence[Sequence[object]]) -> str:
    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(colunas)
    for linha in linhas:
        escritor.writerow([_celula(v) for v in linha])
    return saida.getvalue()
