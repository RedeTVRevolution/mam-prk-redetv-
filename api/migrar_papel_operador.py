"""Migração do papel Operador (#664): `make migrar-papel-operador`.

`operador` deixou de existir; quem o tinha passa a ser `consulta` (as permissões eram as
mesmas). Troca-o em cada documento de `papeis_de_usuarios` do banco de segurança, sem repetir
`consulta` e na ordem canônica; só grava o documento que tinha `operador`, então repetir não
muda nada. Roda em cada ambiente ANTES do deploy do código novo e de novo logo antes dele,
com a atribuição de papéis parada: depois do deploy, `["operador"]` viraria `[]` (sem permissão).
"""

import os
import sys
from itertools import batched
from typing import Any

from api.bancos import cliente_da_colecao
from api.nuvem import COLECAO_DE_PAPEIS
from api.papeis import Papel, em_ordem

LOTE = 400  # o limite do Firestore é 500 gravações por lote


def migrar(colecao: Any, cliente: Any) -> int:
    """Devolve quantos documentos trocou."""
    a_gravar: list[tuple[Any, list[Papel]]] = []
    for doc in colecao.stream():
        papeis = (doc.to_dict() or {}).get("papeis")
        if isinstance(papeis, list) and "operador" in papeis:
            novos = ["consulta" if p == "operador" else p for p in papeis]
            a_gravar.append((doc.reference, em_ordem(novos)))
    for lote in batched(a_gravar, LOTE):
        escrita = cliente.batch()
        for referencia, papeis in lote:
            escrita.update(referencia, {"papeis": papeis})
        escrita.commit()
    return len(a_gravar)


def main() -> int:
    cliente = cliente_da_colecao(os.environ["GCP_PROJECT_ID"], COLECAO_DE_PAPEIS)
    print(f"trocados: {migrar(cliente.collection(COLECAO_DE_PAPEIS), cliente)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
