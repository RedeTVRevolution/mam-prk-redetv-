"""`make registrar-webhook SISTEMA=<nome> URL=<https>`: registra o webhook de um sistema
(E7, #705) e mostra o segredo uma vez só.

A URL vai ao Firestore e o segredo ao Secret Manager (`WEBHOOK_SEGREDOS`, que o
Terraform dá como `webhook_segredos`). Quem roda precisa ler e gravar versões nesse
segredo (dono do projeto, por exemplo).
"""

import os
import sys

from api.bancos import cliente_do_firestore
from api.cofre_secret_manager import cofre_do_ambiente
from api.nuvem import RepositorioDeWebhooksFirestore
from api.webhook import registrar_webhook_main

if __name__ == "__main__":
    projeto = os.environ.get("GCP_PROJECT_ID")
    cofre = cofre_do_ambiente(os.environ)
    if not projeto or cofre is None:
        sys.exit("defina GCP_PROJECT_ID e WEBHOOK_SEGREDOS")
    repositorio = RepositorioDeWebhooksFirestore(cliente_do_firestore(projeto))
    sys.exit(registrar_webhook_main(sys.argv[1:], cofre, repositorio))
