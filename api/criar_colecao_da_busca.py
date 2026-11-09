"""`make criar-colecao-da-busca` (#117): as duas coleções e só o índice ANN dos planos; idempotente."""

import os
import sys

from api.agent_retrieval import (
    ConfigDaBusca,
    EsquemaIncompativel,
    criar_colecao,
    indices_com_filtros_diferentes,
    transporte_http,
)

if __name__ == "__main__":
    config = ConfigDaBusca.do_ambiente(os.environ)
    transporte = transporte_http()
    try:
        acrescentados = criar_colecao(config, transporte)
    except EsquemaIncompativel as erro:
        sys.exit(str(erro))
    print("Coleções e índice da busca prontos.")
    if acrescentados:
        print(
            f"Campos acrescentados ao esquema: {', '.join(acrescentados)}. "
            "Rode `make reindexar`: os registros já gravados só são achados depois disso."
        )
    for indice, faltam in indices_com_filtros_diferentes(config, transporte).items():
        print(
            f"ATENÇÃO: o índice {indice} foi criado sem os campos de filtro "
            f"{', '.join(faltam)}, e o PATCH não os acrescenta. Recrie o índice (apague-o "
            "e rode `make criar-colecao-da-busca` de novo): nada foi apagado aqui."
        )
