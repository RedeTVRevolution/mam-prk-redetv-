"""`make criar-colecao-da-busca` (#117): as duas coleções e só o índice ANN dos planos; idempotente."""

import argparse
import os
import sys
from time import sleep

from api.agent_retrieval import (
    ConfigDaBusca,
    EsquemaIncompativel,
    criar_colecao,
    indices_com_filtros_diferentes,
    transporte_http,
)

# O deploy concede o papel da busca à mam-terraform no apply logo antes (papel_vertex.tf), e o
# IAM leva até 7 min para propagar um papel novo: até lá a criação recebe 403.
ESPERA_DO_IAM_S = 30
ESPERAS_DO_IAM = 16


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
    # Só o deploy espera: o alvo manual roda com um papel que já existe.
    esperas = ESPERAS_DO_IAM if args.personificar else 0
    while True:
        try:
            criar_colecao(config, transporte, ao_acrescentar=_avisar_reindexacao)
            break
        except EsquemaIncompativel as erro:
            sys.exit(str(erro))
        except RuntimeError as erro:
            if "HTTP 403" not in str(erro) or not esperas:
                raise
            esperas -= 1
            print(
                f"403 da busca: o papel novo ainda propaga; nova tentativa em {ESPERA_DO_IAM_S} s.",
                flush=True,
            )
            sleep(ESPERA_DO_IAM_S)
    print("Coleções e índice da busca prontos.")
    for indice, faltam in indices_com_filtros_diferentes(config, transporte).items():
        print(
            f"ATENÇÃO: o índice {indice} foi criado sem os campos de filtro "
            f"{', '.join(faltam)}, e o PATCH não os acrescenta. Recrie o índice (apague-o "
            "e rode `make criar-colecao-da-busca` de novo): nada foi apagado aqui."
        )


if __name__ == "__main__":
    main()
