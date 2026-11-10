"""Limpeza única das coleções de segurança antigas do banco padrão (#530).

Papéis, chaves de API e auditoria moram no banco de segurança (#368/#465); as cópias que
sobraram no `(default)` são dado de teste. `make limpar-banco-padrao` só conta e mostra
(`--listar`, o padrão); `--apagar` apaga. Toca só o `(default)` e só essas três coleções.
"""

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from google.cloud import firestore

from api.bancos import BANCO_PADRAO, COLECOES_DE_SEGURANCA

LOTE = 400


def limpar(
    projeto: str,
    banco: str,
    colecoes: Sequence[str],
    apagar: bool,
    fabrica: Callable[..., Any],
) -> dict[str, int]:
    """Conta (e, com `apagar`, apaga) os documentos das `colecoes` no `banco`."""
    if banco != BANCO_PADRAO:
        raise ValueError(f"só o banco {BANCO_PADRAO} pode ser limpo, não {banco!r}")
    for colecao in colecoes:
        if colecao not in COLECOES_DE_SEGURANCA:
            raise ValueError(f"coleção fora das três de segurança: {colecao!r}")
    cliente = fabrica(project=projeto, database=banco)
    contagens: dict[str, int] = {}
    for colecao in colecoes:
        documentos = list(cliente.collection(colecao).select([]).stream())
        contagens[colecao] = len(documentos)
        if apagar:
            for inicio in range(0, len(documentos), LOTE):
                lote = cliente.batch()
                for documento in documentos[inicio : inicio + LOTE]:
                    lote.delete(documento.reference)
                lote.commit()
    return contagens


def main(
    argv: Sequence[str] | None = None,
    ambiente: Mapping[str, str] | None = None,
    fabrica: Callable[..., Any] = firestore.Client,
) -> int:
    ambiente = os.environ if ambiente is None else ambiente
    modo = argparse.ArgumentParser(description=__doc__)
    grupo = modo.add_mutually_exclusive_group()
    grupo.add_argument("--listar", action="store_true", help="só conta (o padrão)")
    grupo.add_argument("--apagar", action="store_true", help="apaga os documentos")
    args = modo.parse_args(argv)
    contagens = limpar(
        ambiente["GCP_PROJECT_ID"],
        BANCO_PADRAO,
        sorted(COLECOES_DE_SEGURANCA),
        args.apagar,
        fabrica,
    )
    verbo = "apagados" if args.apagar else "encontrados (nada apagado)"
    for colecao, total in contagens.items():
        print(f"{colecao}: {total} documentos {verbo} no banco {BANCO_PADRAO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
