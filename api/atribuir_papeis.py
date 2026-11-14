"""`make atribuir-papeis EMAIL=... PAPEIS=...`: grava os papéis de uma conta (E3).

O uid vem do Identity Platform (busca por e-mail, com as credenciais da máquina);
os papéis vão para o Firestore. A busca na nuvem não tem teste automático.
"""

import os
import sys

from api.bancos import cliente_da_colecao
from api.clientes_de_nuvem import sessao_autenticada
from api.nuvem import COLECAO_DE_PAPEIS, RepositorioDePapeisFirestore
from api.papeis import ContaNaoEncontrada, atribuir_papeis_main


def achar_uid(projeto: str, email: str) -> str:
    sessao = sessao_autenticada()
    resposta = sessao.post(
        f"https://identitytoolkit.googleapis.com/v1/projects/{projeto}/accounts:lookup",
        json={"email": [email]},
        headers={"x-goog-user-project": projeto},
        timeout=30,
    )
    resposta.raise_for_status()
    usuarios = resposta.json().get("users", [])
    if not usuarios:
        raise ContaNaoEncontrada(email)
    return str(usuarios[0]["localId"])


if __name__ == "__main__":
    projeto = os.environ.get("GCP_PROJECT_ID") or sys.exit("defina GCP_PROJECT_ID")
    sys.exit(
        atribuir_papeis_main(
            sys.argv[1:],
            RepositorioDePapeisFirestore(
                cliente_da_colecao(projeto, COLECAO_DE_PAPEIS)
            ),
            lambda email: achar_uid(projeto, email),
        )
    )
