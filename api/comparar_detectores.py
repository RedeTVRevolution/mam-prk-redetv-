"""Compara detectores de corte contra cortes marcados à mão (#545). Só mede.

    python -m api.comparar_detectores VIDEO CORTES_MARCADOS.json

`CORTES_MARCADOS.json` é uma lista de instantes em ms. Para cada detector mostra os cortes
achados, a precisão (dos achados, quantos são marcados), a cobertura (dos marcados, quantos
foram achados) e o tempo. Trocar de detector é decisão da pessoa, com estes números.

O detector atual (`api/cortes.py`) não precisa de nada a mais. Os outros dois não são
dependência do projeto nem entram na imagem de produção: instale só onde for medir
(`uv pip install scenedetect[opencv-headless]`; `uv pip install transnetv2-pytorch`). O que
não estiver instalado sai na tabela como "não instalado". A chamada ao TransNetV2 segue a
API do pacote e não foi exercitada aqui.
"""

import importlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.cortes import detectar_cortes

TOLERANCIA_PADRAO_MS = 200


@dataclass(frozen=True)
class Medida:
    acertos: int
    detectados: int
    marcados: int
    precisao: float | None  # None se nada foi detectado
    cobertura: float | None  # None se nada foi marcado


def medir(
    detectados: Sequence[int], marcados: Sequence[int], tolerancia_ms: int
) -> Medida:
    """Cada corte marcado casa com no máximo um detectado, o mais perto dentro da tolerância."""
    livres = sorted(marcados)
    acertos = 0
    for corte in sorted(detectados):
        perto = [m for m in livres if abs(m - corte) <= tolerancia_ms]
        if perto:
            livres.remove(min(perto, key=lambda m: abs(m - corte)))
            acertos += 1
    return Medida(
        acertos=acertos,
        detectados=len(detectados),
        marcados=len(marcados),
        precisao=acertos / len(detectados) if detectados else None,
        cobertura=acertos / len(marcados) if marcados else None,
    )


class NaoInstalado(Exception):
    pass


def _importar(nome: str) -> Any:
    try:
        return importlib.import_module(nome)
    except ImportError:
        raise NaoInstalado(nome) from None


def _adaptativo(video: Path) -> list[int]:
    scenedetect = _importar("scenedetect")
    cenas = scenedetect.detect(str(video), scenedetect.AdaptiveDetector())
    return [round(inicio.get_seconds() * 1000) for inicio, _ in cenas[1:]]


def _transnetv2(video: Path) -> list[int]:
    modulo = _importar("transnetv2")
    modelo = modulo.TransNetV2()
    _, previsao, _ = modelo.predict_video(str(video))
    cenas = modelo.predictions_to_scenes(previsao)
    fps = float(_importar("scenedetect").open_video(str(video)).frame_rate)
    return [round(int(inicio) / fps * 1000) for inicio, _ in cenas[1:]]


DETECTORES: dict[str, Callable[[Path], list[int]]] = {
    "ffmpeg scene 0,3 (atual)": detectar_cortes,
    "PySceneDetect adaptativo": _adaptativo,
    "TransNetV2": _transnetv2,
}


def comparar(
    video: Path,
    marcados: Sequence[int],
    tolerancia_ms: int = TOLERANCIA_PADRAO_MS,
    detectores: dict[str, Callable[[Path], list[int]]] | None = None,
) -> str:
    linhas = [
        f"{'detector':28} {'achados':>8} {'precisão':>9} {'cobertura':>10} {'tempo_s':>8}"
    ]
    for nome, detectar in (detectores or DETECTORES).items():
        inicio = time.monotonic()
        try:
            achados = detectar(video)
        except NaoInstalado:
            linhas.append(f"{nome:28} não instalado")
            continue
        segundos = time.monotonic() - inicio

        def pct(x: float | None) -> str:
            return "-" if x is None else f"{x:.0%}"

        m = medir(achados, marcados, tolerancia_ms)
        linhas.append(
            f"{nome:28} {m.detectados:>8} {pct(m.precisao):>9} {pct(m.cobertura):>10} "
            f"{segundos:>8.1f}"
        )
    linhas.append(
        f"({len(marcados)} cortes marcados; tolerância de {tolerancia_ms} ms)"
    )
    return "\n".join(linhas)


def main(argumentos: list[str]) -> int:
    if len(argumentos) != 2:
        print(
            "uso: python -m api.comparar_detectores VIDEO CORTES_MARCADOS.json",
            file=sys.stderr,
        )
        return 2
    video, arquivo = argumentos
    print(comparar(Path(video), json.loads(Path(arquivo).read_text())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
