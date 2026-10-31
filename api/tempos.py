"""Regra de tempos: ajusta os tempos da decupagem aos cortes de câmera.

Os planos são os intervalos entre cortes, cada um com a descrição do plano do
modelo com que mais se sobrepõe; aparições e comerciais vão ao corte mais
próximo só se ele estiver a até 1 s; menções, fala e `mencao_editorial` seguem as próprias palavras.
Quando a regra muda um item, os tempos originais ficam em
`inicio_modelo_ms` e `fim_modelo_ms`.
"""

from bisect import bisect_left
from collections.abc import Sequence
from itertools import pairwise

from api.decupagem import Decupagem, Plano, _Intervalo

LIMITE_DE_AJUSTE_MS = 1000


def _mais_proximo(cortes: Sequence[int], tempo_ms: int) -> int:
    """Corte mais próximo de `tempo_ms` (o anterior, num empate)."""
    i = bisect_left(cortes, tempo_ms)
    candidatos = cortes[max(i - 1, 0) : i + 1]
    return min(candidatos, key=lambda c: (abs(c - tempo_ms), c))


def _ajustar[T: _Intervalo](item: T, cortes: Sequence[int], limite_ms: int | None) -> T:
    def ponta(tempo_ms: int) -> int:
        corte = _mais_proximo(cortes, tempo_ms)
        if limite_ms is not None and abs(corte - tempo_ms) > limite_ms:
            return tempo_ms
        return corte

    inicio, fim = ponta(item.inicio_ms), ponta(item.fim_ms)
    if inicio >= fim or (inicio, fim) == (item.inicio_ms, item.fim_ms):
        return item
    # Numa segunda passada, os tempos do modelo já guardados ficam.
    if item.inicio_modelo_ms is None:
        modelo = {"inicio_modelo_ms": item.inicio_ms, "fim_modelo_ms": item.fim_ms}
    else:
        modelo = {}
    return item.model_copy(update={"inicio_ms": inicio, "fim_ms": fim, **modelo})


def _sobreposicao(a: _Intervalo, inicio_ms: int, fim_ms: int) -> int:
    return min(a.fim_ms, fim_ms) - max(a.inicio_ms, inicio_ms)


def _planos_pelos_cortes(planos: Sequence[Plano], cortes: Sequence[int]) -> list[Plano]:
    """Um plano por intervalo entre cortes; sem plano do modelo, nenhum.

    O intervalo herda o plano do modelo com que mais se sobrepõe (o mais perto,
    se nenhum se sobrepõe; o primeiro, num empate). Os tempos do modelo ficam só
    quando o intervalo difere do plano de que herdou.
    """
    if not planos:
        return []
    herdados: list[Plano] = []
    for inicio, fim in pairwise(cortes):
        origem = max(planos, key=lambda p: _sobreposicao(p, inicio, fim))
        if origem.inicio_modelo_ms is None:
            modelo = {
                "inicio_modelo_ms": origem.inicio_ms,
                "fim_modelo_ms": origem.fim_ms,
            }
        else:
            modelo = {}
        mudanca = {"inicio_ms": inicio, "fim_ms": fim}
        if (inicio, fim) == (origem.inicio_ms, origem.fim_ms):
            modelo = {}
        herdados.append(origem.model_copy(update={**mudanca, **modelo}))
    return [
        p.model_copy(update={"id": f"pla{n:03d}"}) for n, p in enumerate(herdados, 1)
    ]


def aplicar_regra_de_tempos(
    decupagem: Decupagem, cortes_ms: Sequence[int]
) -> Decupagem:
    """Devolve uma nova `Decupagem` com os tempos ajustados aos cortes.

    `cortes_ms` é a lista ordenada dos cortes de câmera; o início do vídeo e a
    duração contam como cortes. Sem cortes, nada muda.
    """
    if not cortes_ms:
        return decupagem
    cortes = sorted({0, decupagem.video.duracao_ms, *cortes_ms})

    planos = _planos_pelos_cortes(decupagem.planos, cortes)
    comerciais = [
        c if c.tipo == "mencao_editorial" else _ajustar(c, cortes, LIMITE_DE_AJUSTE_MS)
        for c in decupagem.comerciais
    ]
    pessoas = [
        p.model_copy(
            update={
                "na_imagem": [
                    _ajustar(a, cortes, LIMITE_DE_AJUSTE_MS) for a in p.na_imagem
                ]
            }
        )
        for p in decupagem.pessoas
    ]
    return decupagem.model_copy(
        update={"planos": planos, "comerciais": comerciais, "pessoas": pessoas}
    )
