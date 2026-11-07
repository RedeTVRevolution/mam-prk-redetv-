"""Reconciliação de `pessoas_do_catalogo` (#478): `make recalcular-pessoas-dos-jobs`.

A fusão e a renomeação só leem os vídeos que têm a pessoa em `pessoas_do_catalogo`; a
gravação desse campo falha sem abortar (`api/catalogo_dos_jobs.py`), então um Job pode ter
ficado sem ele. Este comando recalcula o campo de cada Job concluído a partir da Decupagem
entregue, em páginas, e mostra quantos mudaram. Idempotente. É a passada de
`api/preencher_catalogo_dos_jobs.py`, que também grava `marcas_do_catalogo`.
"""

import sys

from api.preencher_catalogo_dos_jobs import main, preencher

__all__ = ["main", "preencher"]

if __name__ == "__main__":
    sys.exit(main())
