"""Cache curto em memória, por instância: painel e relatórios (#453), entendimento da
busca e `macVerify` positivo do KMS (#491).

Sem infraestrutura nova: cada instância do Cloud Run guarda as respostas por chave de filtro
e as joga fora depois de `validade` segundos. Dado recém-gravado aparece em no máximo esse
tempo (mais o das cópias e resumos que a consulta lê). Quem chega junto na mesma chave espera
uma só consulta; o erro não fica guardado.
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any, cast

VALIDADE_DO_CACHE_S = 120.0  # 2 min, dentro do 1 a 5 min do #453
MAXIMO_DE_CHAVES = 64


class CacheCurto:
    def __init__(
        self,
        validade: float = VALIDADE_DO_CACHE_S,
        maximo: int = MAXIMO_DE_CHAVES,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._validade = validade
        self._maximo = maximo
        self._relogio = relogio
        self._trava = threading.Lock()
        self._guardado: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._travas_das_chaves: dict[Hashable, threading.Lock] = {}

    def _valido(self, chave: Hashable) -> tuple[bool, Any]:
        with self._trava:
            achado = self._guardado.get(chave)
            if achado is not None and self._relogio() < achado[0]:
                return True, achado[1]
            return False, None

    def obter[T](self, chave: Hashable, calcular: Callable[[], T]) -> T:
        """O valor da chave, se ainda vale; senão `calcular()` (uma vez só para quem chega
        junto) e guarda."""
        valido, valor = self._valido(chave)
        if valido:
            return cast(T, valor)
        with self._trava:
            trava = self._travas_das_chaves.setdefault(chave, threading.Lock())
        with trava:
            valido, valor = self._valido(chave)
            if valido:
                return cast(T, valor)
            try:
                valor = calcular()
                with self._trava:
                    agora = self._relogio()
                    self._guardado[chave] = (agora + self._validade, valor)
                    self._guardado.move_to_end(chave)
                    for velha in [
                        c for c, (v, _) in self._guardado.items() if v <= agora
                    ]:
                        del self._guardado[velha]
                    while len(self._guardado) > self._maximo:
                        self._guardado.popitem(last=False)
            finally:
                with self._trava:
                    self._travas_das_chaves.pop(chave, None)
            return valor
