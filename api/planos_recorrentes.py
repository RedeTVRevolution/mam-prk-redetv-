"""Planos recorrentes (#546): os planos do vídeo que são a mesma câmera.

Em programa de estúdio, a mesma câmera volta dezenas de vezes. O sinal é o mais barato, sem
modelo e sem vetor de imagem (ADR 0015): o hash perceptual (`hash_do_quadro`) mais o
histograma de cor do quadro-chave de cada plano, que fica no bucket da Decupagem (ADR 0017).
O agrupamento é aglomerativo, com uma restrição: dois planos seguidos não se juntam se o
corte entre eles é real. O enquadramento canônico (#545) não separa mais: o modelo rotula a
mesma câmera ora como plano geral, ora como plano médio, e na marcação 34 de 64 retornos
perdidos eram isso.

Só o plano que tem par ganha `plano_recorrente` (`rec01`, `rec02`… por ordem de aparição);
o plano único fica sem grupo. Os limiares são o chute inicial: a pessoa os calibra com os
números de `python -m api.preencher_planos_recorrentes`; a amostragem para marcar fica em
`api/ferramentas/amostra_dos_planos_recorrentes.py`.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import BytesIO
from itertools import pairwise

from PIL import Image

from api.decupagem import Decupagem, Plano
from api.objetos_job import hash_do_quadro

log = logging.getLogger(__name__)

# Bits de 64 em que dois quadros podem diferir e ainda ser a mesma câmera (14 após a marcação).
LIMITE_DE_BITS = 14
# Bits a partir dos quais o limite entre dois planos seguidos é corte real (não depende do agrupamento).
LIMITE_DO_CORTE_REAL = 10
# Distância de cor (0 a 1: metade da soma das diferenças dos histogramas) do mesmo teor.
LIMITE_DE_COR = 0.25
_BINS = 4  # por canal: 64 faixas de cor no histograma
_LADO_DO_HISTOGRAMA = 32


@dataclass(frozen=True)
class Sinal:
    impressao: int
    cor: tuple[float, ...]


def sinal_do_quadro(imagem: Image.Image) -> Sinal:
    pequena = imagem.convert("RGB").resize((_LADO_DO_HISTOGRAMA,) * 2)
    contagem = [0] * _BINS**3
    pixels = pequena.tobytes()
    for r, g, b in zip(pixels[0::3], pixels[1::3], pixels[2::3], strict=True):
        faixa = (r * _BINS // 256 * _BINS + g * _BINS // 256) * _BINS + b * _BINS // 256
        contagem[faixa] += 1
    total = _LADO_DO_HISTOGRAMA**2
    return Sinal(hash_do_quadro(imagem), tuple(c / total for c in contagem))


def _distancia(a: Sinal, b: Sinal) -> float | None:
    """0 a 1 para quadros do mesmo enquadramento; `None` se passa de um dos limiares."""
    bits = (a.impressao ^ b.impressao).bit_count()
    if bits > LIMITE_DE_BITS:
        return None
    cor = sum(abs(x - y) for x, y in zip(a.cor, b.cor, strict=True)) / 2
    if cor > LIMITE_DE_COR:
        return None
    return max(bits / LIMITE_DE_BITS, cor / LIMITE_DE_COR)


def agrupar(
    sinais: Sequence[Sinal | None],
    corte_real_depois: Sequence[bool],
) -> list[int | None]:
    """O grupo de cada plano (o índice do primeiro do grupo), `None` para o plano sem par.

    Os planos vêm em ordem de tempo. `corte_real_depois[i]` diz que o corte entre o plano `i`
    e o `i + 1` é real. Aglomerativo de ligação completa: os pares mais parecidos juntam
    primeiro, e dois grupos só se juntam se todo par entre eles passa dos limiares e não é um
    par de vizinhos com corte real. Sem sinal (quadro que
    faltou), o plano fica de fora.
    """
    n = len(sinais)
    # ponytail: os pares próximos ficam em memória (O(n²) no pior caso, bem menos na prática);
    # com milhares de planos quase iguais, filtrar por vizinhança do hash.
    proximos: dict[tuple[int, int], float] = {}
    for i, a in enumerate(sinais):
        if a is None:
            continue
        for j in range(i + 1, n):
            outro = sinais[j]
            if outro is None:
                continue
            if (d := _distancia(a, outro)) is not None:
                proximos[(i, j)] = d
    proibidos = {(i, i + 1) for i in range(n - 1) if corte_real_depois[i]}

    def pode(x: int, y: int) -> bool:
        par = (min(x, y), max(x, y))
        return par in proximos and par not in proibidos

    grupos: dict[int, list[int]] = {i: [i] for i in range(n)}
    dono = list(range(n))
    for (i, j), _ in sorted(proximos.items(), key=lambda par: par[1]):
        ga, gb = dono[i], dono[j]
        if ga == gb or not all(pode(x, y) for x in grupos[ga] for y in grupos[gb]):
            continue
        for x in grupos[gb]:
            dono[x] = ga
        grupos[ga] += grupos.pop(gb)
    return [dono[i] if len(grupos[dono[i]]) > 1 else None for i in range(n)]


def _quadro_chave(plano: Plano) -> str | None:
    return plano.quadro or (q[len(q) // 2] if (q := _quadros(plano)) else None)


def _quadros(plano: Plano) -> list[str]:
    return plano.quadros or ([plano.quadro] if plano.quadro else [])


def com_os_planos_recorrentes(
    decupagem: Decupagem,
    ler_quadro: Callable[[str], bytes],
) -> Decupagem:
    """A Decupagem com `plano_recorrente` em cada plano que tem par, no lugar do anterior.

    O limite entre dois planos seguidos é corte real quando os quadros dos dois lados
    diferem mais que `LIMITE_DO_CORTE_REAL`; parecidos, é corte falso (flash, transição), como no
    diagnóstico de `api/planos_curtos.py`. Quadro que não abre deixa o plano sem grupo e o
    corte, por prudência, como real.
    """
    planos = sorted(decupagem.planos, key=lambda p: p.inicio_ms)

    lidos: dict[str, Sinal | None] = {}

    def sinal(caminho: str | None) -> Sinal | None:
        """Cada quadro é lido uma vez: o do meio de um plano é, no plano de um quadro só, o
        das duas bordas."""
        if caminho is None:
            return None
        if caminho not in lidos:
            try:
                lidos[caminho] = sinal_do_quadro(
                    Image.open(BytesIO(ler_quadro(caminho)))
                )
            except Exception:  # noqa: BLE001 - quadro que falta ou não abre só tira o plano do grupo
                log.warning("quadro %s não abriu; o plano fica sem grupo", caminho)
                lidos[caminho] = None
        return lidos[caminho]

    sinais = [sinal(_quadro_chave(p)) for p in planos]
    reais: list[bool] = []
    for a, b in pairwise(planos):
        antes = sinal(_quadros(a)[-1] if _quadros(a) else None)
        depois = sinal(_quadros(b)[0] if _quadros(b) else None)
        reais.append(
            antes is None
            or depois is None
            or (antes.impressao ^ depois.impressao).bit_count() > LIMITE_DO_CORTE_REAL
        )
    reais.append(False)

    grupos = agrupar(sinais, reais)
    nomes: dict[int, str] = {}
    novos: dict[str, str | None] = {}
    for p, g in zip(planos, grupos, strict=True):
        if g is not None:
            nomes.setdefault(g, f"rec{len(nomes) + 1:02d}")
        novos[p.id] = None if g is None else nomes[g]
    return decupagem.model_copy(
        update={
            "planos": [
                p.model_copy(update={"plano_recorrente": novos[p.id]})
                for p in decupagem.planos
            ]
        }
    )


def contagem(decupagem: Decupagem) -> dict[str, int]:
    """Os `planos` agrupados e os `grupos` da Decupagem, para a prévia do preenchimento."""
    ids = [p.plano_recorrente for p in decupagem.planos if p.plano_recorrente]
    return {"planos": len(ids), "grupos": len(set(ids))}
