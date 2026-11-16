"""O que mais de uma ferramenta de linha de comando precisa (#658). Só as ferramentas importam."""

import hashlib
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.modelo_do_job import Job, RepositorioDeJobs

TAMANHO_DA_PAGINA = 500


def jobs_concluidos(
    repositorio: "RepositorioDeJobs",
    *,
    na_lixeira: bool | None,
    tamanho_da_pagina: int = TAMANHO_DA_PAGINA,
) -> Iterator["Job"]:
    """Os Jobs concluídos, página a página. `na_lixeira=None` traz também os da lixeira (as
    cargas que a lixeira marca); `False` os deixa de fora (quem reprocessa)."""
    # Import aqui: api.jobs puxa o app, e as ferramentas que só usam hash ou percentil não.
    from api.modelo_do_job import FiltroDeJobs

    cursor: str | None = None
    while True:
        pagina = repositorio.consultar(
            FiltroDeJobs(
                estados=frozenset({"concluido"}),
                na_lixeira=na_lixeira,
                limite=tamanho_da_pagina,
                cursor=cursor,
            )
        )
        yield from pagina.jobs
        cursor = pagina.proximo_cursor
        if cursor is None:
            return


def hash_estavel(chave: str, digitos: int) -> int:
    """Os primeiros `digitos` hexadecimais do SHA-256 da chave, como inteiro: o sorteio que
    não muda de uma rodada para outra."""
    return int(hashlib.sha256(chave.encode()).hexdigest()[:digitos], 16)


def percentil(valores: list[float], p: int) -> float:
    """O valor na posição mais próxima do percentil (sem interpolar)."""
    ordenados = sorted(valores)
    posicao = max(1, -(-len(ordenados) * p // 100))
    return ordenados[posicao - 1]


def custo_por_hora_do_ambiente(
    ambiente: Mapping[str, str],
) -> float | None:
    """`CUSTO_POR_HORA_USD`, ou `None` sem ele (o custo sai "n/d"). Valor ilegível levanta
    `ValueError`."""
    custo = ambiente.get("CUSTO_POR_HORA_USD")
    return float(custo) if custo else None


def dolar(valor: float | None, *, casas: int = 2, ptbr: bool = True) -> str:
    """`US$ 1.234,56` (`ptbr`) ou `US$ 1234.56`; `n/d` sem valor."""
    if valor is None:
        return "n/d"
    texto = f"{valor:,.{casas}f}" if ptbr else f"{valor:.{casas}f}"
    if ptbr:
        texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"US$ {texto}"
