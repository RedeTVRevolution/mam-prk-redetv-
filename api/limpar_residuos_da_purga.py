"""Limpeza única dos resíduos anteriores à #504; execução manual no dev."""

import os
from collections.abc import Mapping

from google.cloud import firestore

from api.bancos import cliente_do_firestore
from api.copia_bigquery import Transporte, transporte_http
from api.nuvem import COLECAO_DE_JOBS, TiposDeObjetoFirestore

VIDEO_PURGADO = "00e156a84e524193b9c430700197050d"


def limpar(
    cliente: firestore.Client, ambiente: Mapping[str, str], transporte: Transporte
) -> None:
    """Apaga só os resíduos conhecidos e imprime as quantidades confirmadas."""
    decisoes = cliente.collection(ambiente["FIRESTORE_COLECAO_DECISOES_DE_SUGESTAO"])
    if cliente.collection(COLECAO_DE_JOBS).document(VIDEO_PURGADO).get().exists:
        raise RuntimeError("o Job da limpeza ainda existe; confira o ambiente")
    tipos = TiposDeObjetoFirestore(cliente).purgar(VIDEO_PURGADO)
    apagadas = 0
    for doc in decisoes.stream():
        doc.reference.delete()
        apagadas += 1
    print(f"contribuição de tipos: {int(tipos)}; decisões de sugestão: {apagadas}")


def main() -> None:
    projeto = os.environ["GCP_PROJECT_ID"]
    limpar(cliente_do_firestore(projeto), os.environ, transporte_http(projeto))


if __name__ == "__main__":
    main()
