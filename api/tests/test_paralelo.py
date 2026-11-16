"""O auxiliar de chamadas em paralelo que param na primeira falha (#682)."""

import os
import signal
import threading
import time
from collections.abc import Iterator
from types import FrameType

from api.paralelo import em_paralelo


class ItensQueAvisam(list[int]):
    """Avisa quando o último item foi entregue, isto é, quando a submissão acabou."""

    def __init__(self, n: int, avisar: threading.Event) -> None:
        super().__init__(range(n))
        self.avisar = avisar

    def __iter__(self) -> Iterator[int]:
        yield from super().__iter__()
        self.avisar.set()


def test_interrupcao_na_thread_principal_tambem_cancela_o_que_nao_comecou() -> None:
    iniciados: list[int] = []
    interrompido = threading.Event()
    submetidos = threading.Event()

    def ao_interromper(_signo: int, _quadro: FrameType | None) -> None:
        interrompido.set()
        raise KeyboardInterrupt

    def chamar(i: int) -> int:
        iniciados.append(i)
        if (
            i == 0
        ):  # com tudo submetido, a principal espera o resultado: o Ctrl+C chega aqui
            submetidos.wait(timeout=5)
            os.kill(os.getpid(), signal.SIGINT)
            interrompido.wait(timeout=5)
            time.sleep(0.2)  # só dá à thread principal o tempo de desfazer a pilha
        return i

    anterior = signal.signal(signal.SIGINT, ao_interromper)
    try:
        try:
            em_paralelo(ItensQueAvisam(6, submetidos), chamar, 1)
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("a interrupção deveria subir")
    finally:
        signal.signal(signal.SIGINT, anterior)

    assert iniciados == [0]
