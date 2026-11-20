"""`make criar-colecao-da-busca` (#117): as duas coleções e só o índice ANN dos planos; idempotente."""

import argparse
import os
import sys

from api.agent_retrieval import (
    ConfigDaBusca,
    EsquemaIncompativel,
    criar_colecao,
    indices_com_filtros_diferentes,
    transporte_http,
)


def _avisar_reindexacao(campos: list[str]) -> None:
    print(
        f"Campos acrescentados ao esquema: {', '.join(campos)}. "
        "Rode `make reindexar`: os registros já gravados só são achados depois disso.",
        flush=True,
    )


def main(argv: list[str] | None = None) -> None:
    analisador = argparse.ArgumentParser()
    # Só o deploy pede a impersonação: a credencial federada do CD não tem papel próprio. O alvo
    # manual do Makefile roda sem o argumento, com as credenciais de quem roda, como sempre.
    analisador.add_argument("--personificar", metavar="CONTA")
    args = analisador.parse_args(argv)
    config = ConfigDaBusca.do_ambiente(os.environ)
    transporte = (
        transporte_http(personificar=args.personificar)
        if args.personificar
        else transporte_http()
    )
    try:
        criar_colecao(config, transporte, ao_acrescentar=_avisar_reindexacao)
    except EsquemaIncompativel as erro:
        sys.exit(str(erro))
    print("Coleções e índice da busca prontos.")
    for indice, faltam in indices_com_filtros_diferentes(config, transporte).items():
        print(
            f"ATENÇÃO: o índice {indice} foi criado sem os campos de filtro "
            f"{', '.join(faltam)}, e o PATCH não os acrescenta. Recrie o índice (apague-o "
            "e rode `make criar-colecao-da-busca` de novo): nada foi apagado aqui."
        )


if __name__ == "__main__":
    main()
