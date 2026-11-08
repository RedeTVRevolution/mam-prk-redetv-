"""Em qual dispositivo os Jobs de transcrição e de OCR rodam, lido da configuração.

`DISPOSITIVO` vale `cpu` (padrão) ou `gpu`. Pedir GPU numa instância sem GPU é erro, e
nunca motivo para cair para a CPU em silêncio. CPU fica para os testes locais (#500).
"""

import os
from collections.abc import Mapping
from typing import Literal

Dispositivo = Literal["cpu", "gpu"]
VARIAVEL = "DISPOSITIVO"


class DispositivoIndisponivel(RuntimeError):
    """A configuração pede um dispositivo que a instância não tem."""


def ler_dispositivo(ambiente: Mapping[str, str] | None = None) -> Dispositivo:
    valor = (os.environ if ambiente is None else ambiente).get(VARIAVEL, "cpu")
    valor = valor.strip().lower() or "cpu"
    if valor not in ("cpu", "gpu"):
        raise ValueError(f"{VARIAVEL}={valor!r} não é válido: use 'cpu' ou 'gpu'.")
    return valor  # type: ignore[return-value]


def exigir_gpu(quantas: int, biblioteca: str) -> None:
    if quantas < 1:
        raise DispositivoIndisponivel(
            f"{VARIAVEL}=gpu, mas {biblioteca} não vê nenhuma GPU nesta instância: "
            "a imagem sem GPU, a instância sem GPU ou o driver faltando. "
            f"Não caio para a CPU em silêncio; ponha {VARIAVEL}=cpu para rodar em CPU."
        )
