"""`make definir-aprovacao TIPOS=...`: grava os tipos de correção que exigem aprovação (E3)."""

import os
import sys

from google.cloud import firestore

from api.aprovacao import definir_aprovacao_main
from api.nuvem import RepositorioDeAprovacaoFirestore

if __name__ == "__main__":
    projeto = os.environ.get("GCP_PROJECT_ID") or sys.exit("defina GCP_PROJECT_ID")
    sys.exit(
        definir_aprovacao_main(
            sys.argv[1:],
            RepositorioDeAprovacaoFirestore(firestore.Client(project=projeto)),
        )
    )
