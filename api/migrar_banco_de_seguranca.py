"""Migração das coleções de segurança para o banco novo (#465): `make migrar-banco-de-seguranca`.

Copia `papeis_de_usuarios`, `chaves_de_api` e `auditoria` do `(default)` para o banco de
segurança (#368), com os mesmos ids e campos. Cada documento é regravado no mesmo id, então
repetir não duplica nada. Não apaga a origem: as cópias antigas saem num ticket à parte,
depois da conferência das contagens.
"""

import logging
import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

from google.cloud import firestore

from api.bancos import (
    BANCO_PADRAO,
    COLECOES_DE_SEGURANCA,
    banco_da_colecao,
    cliente_da_colecao,
)

log = logging.getLogger(__name__)

LOTE = 400


def migrar_colecao(origem: Any, destino: Any, colecao: str) -> dict[str, int]:
    """Copia a `colecao` de `origem` para `destino`; devolve as contagens nos dois bancos."""
    lote = destino.batch()
    pendentes = 0
    for documento in origem.collection(colecao).stream():
        lote.set(
            destino.collection(colecao).document(documento.id), documento.to_dict()
        )
        pendentes += 1
        if pendentes == LOTE:
            lote.commit()
            lote = destino.batch()
            pendentes = 0
    if pendentes:
        lote.commit()
    return {
        "origem": _contar(origem, colecao),
        "destino": _contar(destino, colecao),
    }


def _contar(cliente: Any, colecao: str) -> int:
    return sum(1 for _ in cliente.collection(colecao).select([]).stream())


def migrar(
    projeto: str,
    ambiente: Mapping[str, str],
    fabrica: Callable[..., Any] = firestore.Client,
) -> dict[str, dict[str, int]]:
    """Migra as três coleções. Recusa se o banco de segurança é o próprio `(default)`."""
    resultado: dict[str, dict[str, int]] = {}
    origem = fabrica(project=projeto, database=BANCO_PADRAO)
    for colecao in sorted(COLECOES_DE_SEGURANCA):
        if banco_da_colecao(colecao, ambiente) == BANCO_PADRAO:
            raise ValueError(
                "FIRESTORE_BANCO_DE_SEGURANCA vazia ou igual a (default): nada a migrar"
            )
        destino = cliente_da_colecao(projeto, colecao, ambiente, fabrica)
        resultado[colecao] = migrar_colecao(origem, destino, colecao)
    return resultado


def main() -> int:
    try:
        resultado = migrar(os.environ["GCP_PROJECT_ID"], os.environ)
    except ValueError as erro:
        print(erro, file=sys.stderr)
        return 2
    divergiu = False
    for colecao, contagem in resultado.items():
        print(f"{colecao}: origem {contagem['origem']}, destino {contagem['destino']}")
        divergiu = divergiu or contagem["destino"] < contagem["origem"]
    return 1 if divergiu else 0


if __name__ == "__main__":
    sys.exit(main())
