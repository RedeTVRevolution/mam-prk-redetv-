"""`make carregar-catalogo`: carga inicial do catálogo de pessoas (#108).

Acrescenta ao Firestore as pessoas do `programas.toml` que ainda não estão lá;
rodar de novo não duplica ninguém. Usa as credenciais da máquina; sem teste
automático contra a nuvem (a carga em si é testada com o dublê).
"""

import os
import sys

from google.cloud import firestore

from api.catalogo import carregar_programas
from api.nuvem import CatalogoFirestore
from api.programas import DADOS

if __name__ == "__main__":
    projeto = os.environ.get("GCP_PROJECT_ID") or sys.exit("defina GCP_PROJECT_ID")
    entraram = carregar_programas(
        CatalogoFirestore(firestore.Client(project=projeto)), DADOS
    )
    print(f"{entraram} pessoa(s) acrescentada(s) ao catálogo")
