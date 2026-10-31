"""`make criar-colecao-da-busca` (#117): a coleção de momentos e o índice ANN; idempotente."""

import os

from api.agent_retrieval import ConfigDaBusca, criar_colecao, transporte_http

if __name__ == "__main__":
    config = ConfigDaBusca.do_ambiente(os.environ)
    criar_colecao(config, transporte_http())
    print("Coleção e índice da busca prontos.")
