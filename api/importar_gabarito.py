"""Importa o gabarito de famosos (#353): CSV do comparador -> casos do conjunto de regressão.

Comando: `make importar-gabarito [GABARITO=evals/gabarito] [PASTA=evals/regressao/casos]`.
Cada `*.csv` da pasta do gabarito (primeira linha `# sha256: <hex>`, depois
`tipo,identidade,inicio,fim`) vira um caso `anotado`. O id do caso sai do vídeo e do
trecho, então importar de novo regrava o mesmo arquivo, sem duplicar; se o trecho do
CSV mudou, o caso anotado antigo do mesmo vídeo sai da pasta.
"""

import sys
from collections.abc import Callable
from pathlib import Path

from api.comparador import ler_gabarito
from api.regressao import (
    PASTA_DOS_CASOS,
    Caso,
    caso_do_gabarito,
    gravar_caso,
    prefixo_do_caso_anotado,
)

PASTA_DO_GABARITO = Path("evals/gabarito")


def importar(
    gabarito: Path, pasta: Path, escrever: Callable[[str], None] = print
) -> list[Caso]:
    arquivos = sorted(gabarito.glob("*.csv"))
    if not arquivos:
        raise ValueError(f"nenhum CSV em {gabarito}")
    casos: list[Caso] = []
    for arquivo in arquivos:
        sha256, itens = ler_gabarito(arquivo)
        if not itens:
            raise ValueError(f"{arquivo.name}: sem nenhuma linha de gabarito")
        casos.append(caso_do_gabarito(sha256, itens))
    novos = {c.id for c in casos}
    for caso in casos:
        for antigo in pasta.glob(f"{prefixo_do_caso_anotado(caso.sha256)}*.json"):
            if antigo.stem not in novos:
                antigo.unlink()
        gravar_caso(pasta, caso)
    reservados = sum(c.reservado for c in casos)
    escrever(
        f"{len(casos)} casos gravados em {pasta} "
        f"({reservados} reservados, {len(casos) - reservados} para ajuste)"
    )
    return casos


def main(argumentos: list[str]) -> int:
    gabarito = (
        Path(argumentos[0]) if argumentos and argumentos[0] else PASTA_DO_GABARITO
    )
    pasta = (
        Path(argumentos[1])
        if len(argumentos) > 1 and argumentos[1]
        else PASTA_DOS_CASOS
    )
    try:
        importar(gabarito, pasta)
    except ValueError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
