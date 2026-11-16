"""Chamadas em paralelo que param na primeira falha (#682), para o inventário e a análise
por janelas: cada chamada que não começa poupa até um prazo inteiro do Flex."""

from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, ThreadPoolExecutor
from threading import Event


def em_paralelo[T, R](
    itens: Sequence[T], chamar: Callable[[T], R], maximo: int
) -> list[R]:
    """`chamar` em cada item, no máximo `maximo` ao mesmo tempo; devolve os resultados na
    ordem dos itens. Na primeira falha, os itens que ainda não começaram não começam, e a
    primeira falha que não é cancelamento sobe depois de as em andamento terminarem."""
    falhou = Event()

    def rodar(item: T) -> R:
        if falhou.is_set():
            raise CancelledError
        try:
            return chamar(item)
        except BaseException:
            falhou.set()
            raise

    with ThreadPoolExecutor(max_workers=max(maximo, 1)) as pool:
        futuros = [pool.submit(rodar, i) for i in itens]
        erros = [f.exception() for f in futuros]
    for erro in erros:
        if erro and not isinstance(erro, CancelledError):
            raise erro
    return [f.result() for f in futuros]
