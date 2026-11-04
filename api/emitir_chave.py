"""`make emitir-chave SISTEMA=<nome>`: emite a chave de API de um sistema (E7).

O HMAC sai da chave MAC do Cloud KMS (`KMS_CHAVE_MAC`, o nome completo da chave, que
o Terraform dá como `chave_mac_kms`) ou, sem ela, de uma chave simulada
(`MAC_SIMULADO_CHAVE`, em hexadecimal), só para a máquina local e o emulador.
"""

import os
import sys

from google.cloud import firestore

from api.chaves import main
from api.mac_kms import mac_do_ambiente
from api.nuvem import RepositorioDeChavesFirestore

if __name__ == "__main__":
    projeto = os.environ.get("GCP_PROJECT_ID")
    mac = mac_do_ambiente(os.environ)
    if not projeto or not mac:
        sys.exit(
            "defina GCP_PROJECT_ID e KMS_CHAVE_MAC (ou, só na máquina local, "
            "MAC_SIMULADO_CHAVE em hexadecimal)"
        )
    sys.exit(
        main(
            sys.argv[1:],
            mac,
            RepositorioDeChavesFirestore(firestore.Client(project=projeto)),
        )
    )
