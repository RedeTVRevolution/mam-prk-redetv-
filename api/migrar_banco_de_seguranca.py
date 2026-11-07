"""Migração das coleções de segurança para o banco novo (#465): `make migrar-banco-de-seguranca`.

Copia `papeis_de_usuarios`, `chaves_de_api` e `auditoria` do `(default)` para o banco de
segurança (#368), com os mesmos ids e campos. Só grava os ids que o destino ainda não tem:
repetir não duplica nada, e rodar de novo depois do deploy não desfaz o que os serviços já
gravaram no banco novo (uma chave revogada ali não volta a valer). Não apaga a origem: as
cópias antigas saem num ticket à parte, depois da conferência das contagens.
"""

import os
import sys
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from google.cloud import firestore

from api.bancos import (
    BANCO_PADRAO,
    COLECOES_DE_SEGURANCA,
    banco_da_colecao,
    cliente_da_colecao,
)

LOTE = 400


class Contagem(NamedTuple):
    origem: int
    destino: int
    copiados: int
    faltando: int


def migrar_colecao(origem: Any, destino: Any, colecao: str) -> Contagem:
    """Copia para `destino` os documentos da `colecao` que ele ainda não tem."""
    ja_no_destino = _ids(destino, colecao)
    lote = destino.batch()
    pendentes = copiados = 0
    for documento in origem.collection(colecao).stream():
        if documento.id in ja_no_destino:
            continue
        lote.set(
            destino.collection(colecao).document(documento.id), documento.to_dict()
        )
        pendentes += 1
        copiados += 1
        if pendentes == LOTE:
            lote.commit()
            lote = destino.batch()
            pendentes = 0
    if pendentes:
        lote.commit()
    ids_na_origem, ids_no_destino = _ids(origem, colecao), _ids(destino, colecao)
    return Contagem(
        origem=len(ids_na_origem),
        destino=len(ids_no_destino),
        copiados=copiados,
        faltando=len(ids_na_origem - ids_no_destino),
    )


def _ids(cliente: Any, colecao: str) -> set[str]:
    return {doc.id for doc in cliente.collection(colecao).select([]).stream()}


def migrar(
    projeto: str,
    ambiente: Mapping[str, str],
    fabrica: Callable[..., Any] = firestore.Client,
) -> dict[str, Contagem]:
    """Migra as três coleções. Recusa se o banco de segurança é o próprio `(default)`."""
    if any(
        banco_da_colecao(c, ambiente) == BANCO_PADRAO for c in COLECOES_DE_SEGURANCA
    ):
        raise ValueError(
            "FIRESTORE_BANCO_DE_SEGURANCA vazia ou igual a (default): nada a migrar"
        )
    origem = fabrica(project=projeto, database=BANCO_PADRAO)
    return {
        colecao: migrar_colecao(
            origem, cliente_da_colecao(projeto, colecao, ambiente, fabrica), colecao
        )
        for colecao in sorted(COLECOES_DE_SEGURANCA)
    }


def main() -> int:
    try:
        resultado = migrar(os.environ["GCP_PROJECT_ID"], os.environ)
    except ValueError as erro:
        print(erro, file=sys.stderr)
        return 2
    for colecao, c in resultado.items():
        print(
            f"{colecao}: origem {c.origem}, destino {c.destino}, "
            f"copiados agora {c.copiados}, faltando no destino {c.faltando}"
        )
    return 1 if any(c.faltando for c in resultado.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
