"""`make listar-chaves SISTEMA=...` e `make revogar-chave ID=...` (E7).

Usa o mesmo Firestore do `emitir_chave`; a listagem nunca mostra hash nem chave.
"""

import os
import sys

from google.cloud import firestore

from api.chaves import listar_chaves_main, revogar_chave_main
from api.nuvem import RepositorioDeChavesFirestore

if __name__ == "__main__":
    projeto = os.environ.get("GCP_PROJECT_ID")
    if not projeto or len(sys.argv) < 2 or sys.argv[1] not in ("listar", "revogar"):
        sys.exit("defina GCP_PROJECT_ID; uso: gerir_chaves listar|revogar <valor>")
    repositorio = RepositorioDeChavesFirestore(firestore.Client(project=projeto))
    comando = listar_chaves_main if sys.argv[1] == "listar" else revogar_chave_main
    sys.exit(comando(sys.argv[2:], repositorio))
