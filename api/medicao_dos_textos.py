"""Medição dos textos na tela: os tempos vêm dos quadros lidos pelo OCR, não do Gemini.

Para cada texto lido pelo Gemini, procura o mesmo texto quadro a quadro na
`LeituraDaTela` (normalizado e comparado com `SequenceMatcher`; linhas vizinhas do
quadro são juntas, porque uma tarja de duas linhas pode vir numa linha só). Segundos
seguidos com o texto formam uma aparição; uma falha isolada do OCR não a parte, uma
tela preta ou um texto que sai e volta partem. O tempo do Gemini só escolhe a
aparição quando o mesmo texto aparece várias vezes. Um texto que o OCR não acha fica
com o tempo do Gemini e `medido=False`, e conta como dúvida no escalonamento.
"""

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

from api.decupagem import Decupagem, TextoNaTela
from api.leitura_da_tela import LeituraDaTela, LinhaLida

LIMIAR_DE_SEMELHANCA_DO_OCR = 0.8
TOLERANCIA_DE_QUADROS = 1
# Uma tarja passa de poucas linhas; juntar mais só custa comparações.
MAXIMO_DE_LINHAS_JUNTAS = 4

_Aparicao = tuple[int, int]


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).split())


def _candidatos(linhas: list[LinhaLida]) -> list[str]:
    """Cada linha e cada grupo de linhas vizinhas (na ordem de leitura), normalizados."""
    ordem = sorted(linhas, key=lambda x: (x.caixa.y, x.caixa.x))
    textos = [_normalizar(x.texto) for x in ordem]
    return [
        " ".join(t for t in textos[i : i + n] if t)
        for n in range(1, MAXIMO_DE_LINHAS_JUNTAS + 1)
        for i in range(len(textos) - n + 1)
    ]


def _segundos_com_o_texto(
    alvo: str, leitura: LeituraDaTela, limiar: float
) -> list[int]:
    return sorted(
        q.segundo
        for q in leitura.quadros
        if any(
            SequenceMatcher(None, alvo, c).ratio() >= limiar
            for c in _candidatos(q.linhas)
            if c
        )
    )


def _aparicoes(
    segundos: list[int], tolerancia: int, duracao_ms: int
) -> list[_Aparicao]:
    """Segundos seguidos viram `(inicio_ms, fim_ms)`; o quadro do segundo `s` vale até `s + 1`."""
    blocos: list[list[int]] = []
    for s in segundos:
        if blocos and s - blocos[-1][-1] - 1 <= tolerancia:
            blocos[-1][-1] = s
        else:
            blocos.append([s, s])
    return [
        (min(i * 1000, duracao_ms), min((f + 1) * 1000, duracao_ms)) for i, f in blocos
    ]


def _distancia(texto: TextoNaTela, aparicao: _Aparicao) -> tuple[int, int]:
    inicio, fim = aparicao
    sobreposto = min(fim, texto.fim_ms) - max(inicio, texto.inicio_ms)
    return (-max(sobreposto, 0), abs(inicio - texto.inicio_ms))


def medir_textos(
    decupagem: Decupagem,
    leitura: LeituraDaTela,
    *,
    limiar: float = LIMIAR_DE_SEMELHANCA_DO_OCR,
    tolerancia: int = TOLERANCIA_DE_QUADROS,
    trecho_ms: tuple[int, int] | None = None,
) -> Decupagem:
    """Troca os tempos de `textos_na_tela` pelos medidos nos quadros.

    `trecho_ms` limita as aparições que não casaram com nenhum item do Gemini às que
    tocam o trecho (a análise de uma janela não acrescenta o que é de outra).
    """
    duracao_ms = decupagem.video.duracao_ms
    grupos: dict[str, list[TextoNaTela]] = defaultdict(list)
    for t in decupagem.textos_na_tela:
        grupos[_normalizar(t.texto)].append(t)

    resultado: list[TextoNaTela] = []
    for alvo, itens in grupos.items():
        aparicoes = (
            _aparicoes(
                _segundos_com_o_texto(alvo, leitura, limiar), tolerancia, duracao_ms
            )
            if alvo
            else []
        )
        if not aparicoes:
            resultado += [t.model_copy(update={"medido": False}) for t in itens]
            continue
        livres = list(aparicoes)
        for t in sorted(itens, key=lambda x: x.inicio_ms):
            if not livres:
                break  # item repetido: a aparição já tem dono
            escolhida = min(livres, key=lambda a: _distancia(t, a))
            livres.remove(escolhida)
            resultado.append(_com_tempo(t, escolhida))
        modelo = itens[0]
        resultado += [
            _com_tempo(modelo, a, do_modelo=False)
            for a in livres
            if trecho_ms is None or (a[0] < trecho_ms[1] and a[1] > trecho_ms[0])
        ]
    resultado.sort(key=lambda t: (t.inicio_ms, t.fim_ms))
    return decupagem.model_copy(update={"textos_na_tela": resultado})


def _com_tempo(
    texto: TextoNaTela, aparicao: _Aparicao, *, do_modelo: bool = True
) -> TextoNaTela:
    inicio, fim = aparicao
    mudanca: dict[str, object] = {"inicio_ms": inicio, "fim_ms": fim, "medido": True}
    if (
        do_modelo
        and texto.inicio_modelo_ms is None
        and (inicio, fim)
        != (
            texto.inicio_ms,
            texto.fim_ms,
        )
    ):
        mudanca |= {"inicio_modelo_ms": texto.inicio_ms, "fim_modelo_ms": texto.fim_ms}
    if not do_modelo:
        mudanca |= {"inicio_modelo_ms": None, "fim_modelo_ms": None}
    return texto.model_copy(update=mudanca)
