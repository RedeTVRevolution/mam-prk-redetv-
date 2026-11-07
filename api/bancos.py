"""Em qual banco do Firestore cada coleção mora (#368).

Papéis, chaves de API e auditoria ficam num banco só de segurança, fora do alcance dos
Jobs que abrem conteúdo hostil. O nome do banco vem de `FIRESTORE_BANCO_DE_SEGURANCA`
(o Terraform o entrega aos serviços); sem a variável, tudo fica no `(default)`.
"""

import os
from collections.abc import Callable, Mapping
from typing import Any

from google.cloud import firestore

from api.nuvem import COLECAO_DA_AUDITORIA, COLECAO_DE_CHAVES, COLECAO_DE_PAPEIS

VARIAVEL_DO_BANCO_DE_SEGURANCA = "FIRESTORE_BANCO_DE_SEGURANCA"
BANCO_PADRAO = "(default)"
COLECOES_DE_SEGURANCA = frozenset(
    {COLECAO_DE_PAPEIS, COLECAO_DE_CHAVES, COLECAO_DA_AUDITORIA}
)


def banco_da_colecao(colecao: str, ambiente: Mapping[str, str] | None = None) -> str:
    """O banco da `colecao`: o de segurança, se ela é de segurança e a variável existe."""
    ambiente = os.environ if ambiente is None else ambiente
    if colecao in COLECOES_DE_SEGURANCA:
        return ambiente.get(VARIAVEL_DO_BANCO_DE_SEGURANCA) or BANCO_PADRAO
    return BANCO_PADRAO


def cliente_da_colecao(
    projeto: str,
    colecao: str,
    ambiente: Mapping[str, str] | None = None,
    fabrica: Callable[..., Any] = firestore.Client,
) -> Any:
    """Cliente do Firestore apontado para o banco onde a `colecao` mora."""
    return fabrica(project=projeto, database=banco_da_colecao(colecao, ambiente))
