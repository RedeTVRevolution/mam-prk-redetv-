"""Diagnóstico dos planos de menos de 1 s (#545): cortes falsos ou cortes reais?

Para cada plano curto, compara com o hash perceptual (`hash_do_quadro`, o mesmo do Job de
objetos) o quadro de cada lado dos dois cortes que o limitam, e os dois vizinhos entre si
(um flash ou uma transição deixa os vizinhos iguais). Só mede; fundir ou não é decisão da
pessoa, com esta tabela.

Roda sobre uma pasta local por vídeo, que a pessoa baixa do dev:

    <pasta>/decupagem.json   a Decupagem gravada
    <pasta>/cortes_ms.json   os `cortes_ms` do Job (opcional; sem ele, os planos são do modelo)
    <pasta>/quadros/*.jpg    os quadros de `plano.quadros`

    python -m api.planos_curtos PASTA [PASTA...]
"""

import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image

from api.decupagem import Decupagem, Plano
from api.objetos_job import hash_do_quadro

LIMITE_CURTO_MS = 1_000
# Bits de 64 em que dois quadros podem diferir e ainda contar como "o mesmo quadro".
# Chute inicial: a pessoa calibra olhando as distâncias da tabela.
BITS_PARECIDOS = 10

Veredito = Literal["provavelmente falso", "provavelmente real", "sem quadros"]


@dataclass(frozen=True)
class LinhaDoDiagnostico:
    video: str
    plano: str
    inicio_ms: int
    duracao_ms: int
    origem: Literal["cortes", "modelo"]
    distancia_na_entrada: int | None
    distancia_na_saida: int | None
    distancia_dos_vizinhos: int | None
    veredito: Veredito


def _quadros(plano: Plano) -> list[str]:
    return plano.quadros or ([plano.quadro] if plano.quadro else [])


def _distancia(a: str | None, b: str | None, ler: Callable[[str], bytes]) -> int | None:
    if a is None or b is None:
        return None
    ha = hash_do_quadro(Image.open(BytesIO(ler(a))))
    hb = hash_do_quadro(Image.open(BytesIO(ler(b))))
    return (ha ^ hb).bit_count()


def diagnosticar(
    decupagem: Decupagem,
    cortes_ms: Sequence[int],
    ler_quadro: Callable[[str], bytes],
    video: str = "",
) -> list[LinhaDoDiagnostico]:
    """Uma linha por plano de menos de 1 s, na ordem do vídeo."""
    planos = sorted(decupagem.planos, key=lambda p: p.inicio_ms)
    linhas = []
    for n, plano in enumerate(planos):
        if plano.fim_ms - plano.inicio_ms >= LIMITE_CURTO_MS:
            continue
        antes = _quadros(planos[n - 1])[-1:] if n > 0 else []
        depois = _quadros(planos[n + 1])[:1] if n + 1 < len(planos) else []
        meus = _quadros(plano)
        entrada = _distancia(
            antes[0] if antes else None, meus[0] if meus else None, ler_quadro
        )
        saida = _distancia(
            meus[-1] if meus else None, depois[0] if depois else None, ler_quadro
        )
        vizinhos = _distancia(
            antes[0] if antes else None, depois[0] if depois else None, ler_quadro
        )
        medidas = [d for d in (entrada, saida, vizinhos) if d is not None]
        if not medidas:
            veredito: Veredito = "sem quadros"
        elif min(medidas) <= BITS_PARECIDOS:
            veredito = "provavelmente falso"
        else:
            veredito = "provavelmente real"
        linhas.append(
            LinhaDoDiagnostico(
                video=video,
                plano=plano.id,
                inicio_ms=plano.inicio_ms,
                duracao_ms=plano.fim_ms - plano.inicio_ms,
                origem="cortes" if cortes_ms else "modelo",
                distancia_na_entrada=entrada,
                distancia_na_saida=saida,
                distancia_dos_vizinhos=vizinhos,
                veredito=veredito,
            )
        )
    return linhas


def diagnosticar_pasta(pasta: Path) -> list[LinhaDoDiagnostico]:
    decupagem = Decupagem.model_validate_json((pasta / "decupagem.json").read_bytes())
    arquivo_de_cortes = pasta / "cortes_ms.json"
    cortes = (
        json.loads(arquivo_de_cortes.read_text()) if arquivo_de_cortes.exists() else []
    )
    return diagnosticar(
        decupagem, cortes, lambda c: (pasta / c).read_bytes(), video=pasta.name
    )


def tabela(linhas: Sequence[LinhaDoDiagnostico]) -> str:
    def d(x: int | None) -> str:
        return "-" if x is None else str(x)

    saida = [
        f"{'vídeo':14} {'plano':8} {'início_ms':>10} {'dur_ms':>7} {'origem':7} "
        + f"{'entra':>5} {'sai':>5} {'viz.':>5}  veredito"
    ]
    for ln in linhas:
        saida.append(
            f"{ln.video[:14]:14} {ln.plano:8} {ln.inicio_ms:>10} {ln.duracao_ms:>7} "
            f"{ln.origem:7} {d(ln.distancia_na_entrada):>5} {d(ln.distancia_na_saida):>5} "
            f"{d(ln.distancia_dos_vizinhos):>5}  {ln.veredito}"
        )
    por_origem = Counter(ln.origem for ln in linhas)
    por_veredito = Counter(ln.veredito for ln in linhas)
    saida.append("")
    saida.append(
        "origem — " + ", ".join(f"{k}: {v}" for k, v in sorted(por_origem.items()))
    )
    saida.append(
        "veredito — " + ", ".join(f"{k}: {v}" for k, v in sorted(por_veredito.items()))
    )
    saida.append(f"(distâncias em bits de 64; parecido = até {BITS_PARECIDOS})")
    return "\n".join(saida)


def main(argumentos: list[str]) -> int:
    if not argumentos:
        print("uso: python -m api.planos_curtos PASTA [PASTA...]", file=sys.stderr)
        return 2
    linhas = [ln for pasta in argumentos for ln in diagnosticar_pasta(Path(pasta))]
    print(tabela(linhas))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
