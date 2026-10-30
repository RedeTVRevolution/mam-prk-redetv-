"""`make emitir-chave SISTEMA=<nome>`: emite a chave de API de um sistema (E7).

O HMAC sai de uma chave MAC simulada (`MAC_SIMULADO_CHAVE`, em hexadecimal), só
para a máquina local e o emulador; a chave MAC do Cloud KMS vem em outro ticket.
"""

import os
import sys

from google.cloud import firestore

from api.chaves import MacSimulado, main
from api.nuvem import RepositorioDeChavesFirestore

if __name__ == "__main__":
    projeto = os.environ.get("GCP_PROJECT_ID")
    chave_mac = os.environ.get("MAC_SIMULADO_CHAVE")
    if not projeto or not chave_mac:
        sys.exit("defina GCP_PROJECT_ID e MAC_SIMULADO_CHAVE (hexadecimal)")
    sys.exit(
        main(
            sys.argv[1:],
            MacSimulado({1: bytes.fromhex(chave_mac)}, versao_atual=1),
            RepositorioDeChavesFirestore(firestore.Client(project=projeto)),
        )
    )
