"""O auxiliar de chamadas em paralelo que param na primeira falha (#682)."""

import signal
import threading
from collections.abc import Iterator
from types import FrameType

import pytest

from api.paralelo import em_paralelo


class ItensQueAvisam(list[int]):
    """Avisa quando o último item foi entregue, isto é, quando a submissão acabou."""

    def __init__(self, n: int, avisar: threading.Event) -> None:
        super().__init__(range(n))
        self.avisar = avisar

    def __iter__(self) -> Iterator[int]:
        yield from super().__iter__()
        self.avisar.set()


def test_interrupcao_na_thread_principal_tambem_cancela_o_que_nao_comecou(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iniciados: list[int] = []
    cancelamento_marcado = threading.Event()
    submetidos = threading.Event()

    class EventoQueAvisa(threading.Event):
        def set(self) -> None:
            super().set()
            cancelamento_marcado.set()

    # O auxiliar marca o cancelamento no seu Event; a chamada 0 só termina depois disso.
    monkeypatch.setattr("api.paralelo.Event", EventoQueAvisa)

    interrompido = threading.Event()

    def ao_interromper(_signo: int, _quadro: FrameType | None) -> None:
        interrompido.set()
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # uma interrupção só
        raise KeyboardInterrupt

    def chamar(i: int) -> int:
        iniciados.append(i)
        if (
            i == 0
        ):  # com tudo submetido, a principal espera o resultado: o Ctrl+C chega aqui
            submetidos.wait(timeout=5)
            principal = threading.main_thread().ident or 0
            # O CPython pode perder um sinal que chega no instante em que a principal vai
            # dormir; por isso reenvia até o handler rodar (o prazo só protege contra travar).
            for _ in range(100):
                signal.pthread_kill(principal, signal.SIGINT)
                if interrompido.wait(timeout=0.05):
                    break
            cancelamento_marcado.wait(timeout=5)
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
