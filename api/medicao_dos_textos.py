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
    juntos = {
        " ".join(t for t in textos[i : i + n] if t)
        for n in range(1, MAXIMO_DE_LINHAS_JUNTAS + 1)
        for i in range(len(textos) - n + 1)
    }
    return sorted(c for c in juntos if c)


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


def _sobreposicao(a: tuple[int, int], b: tuple[int, int]) -> int:
    return min(a[1], b[1]) - max(a[0], b[0])


def _distancia(texto: TextoNaTela, aparicao: _Aparicao) -> tuple[int, int]:
    sobreposto = _sobreposicao(aparicao, (texto.inicio_ms, texto.fim_ms))
    return (-max(sobreposto, 0), abs(aparicao[0] - texto.inicio_ms))


class MedicaoDosTextos:
    """Mede os textos de várias decupagens do mesmo vídeo numa só leitura da tela.

    Os candidatos de cada quadro e os segundos de cada texto são calculados uma
    vez: a análise mede cada janela e de novo a consolidada.
    """

    def __init__(
        self,
        leitura: LeituraDaTela,
        *,
        limiar: float = LIMIAR_DE_SEMELHANCA_DO_OCR,
        tolerancia: int = TOLERANCIA_DE_QUADROS,
    ) -> None:
        self._quadros = [(q.segundo, _candidatos(q.linhas)) for q in leitura.quadros]
        self._limiar = limiar
        self._tolerancia = tolerancia
        self._segundos: dict[str, list[int]] = {}

    def _segundos_com_o_texto(self, alvo: str) -> list[int]:
        if alvo not in self._segundos:
            # `b` fixo: o SequenceMatcher guarda a análise do alvo entre os candidatos;
            # as razões rápidas são tetos da `ratio` e descartam a maioria antes dela.
            comparar = SequenceMatcher(None, b=alvo)

            def casa(candidato: str) -> bool:
                comparar.set_seq1(candidato)
                return (
                    comparar.real_quick_ratio() >= self._limiar
                    and comparar.quick_ratio() >= self._limiar
                    and comparar.ratio() >= self._limiar
                )

            self._segundos[alvo] = sorted(
                s for s, candidatos in self._quadros if any(map(casa, candidatos))
            )
        return self._segundos[alvo]

    def medir(
        self, decupagem: Decupagem, trecho_ms: tuple[int, int] | None = None
    ) -> Decupagem:
        """Troca os tempos de `textos_na_tela` pelos medidos nos quadros.

        Com `trecho_ms` (a análise de uma janela), só contam as aparições que tocam
        o trecho: o texto que o OCR não acha ali fica não medido, e a janela não
        acrescenta o que é de outra. Um texto já não medido fica como está: a
        medição da consolidada não o leva para longe da janela que o leu.
        """
        duracao_ms = decupagem.video.duracao_ms
        grupos: dict[str, list[TextoNaTela]] = defaultdict(list)
        resultado: list[TextoNaTela] = []
        for t in decupagem.textos_na_tela:
            if t.medido is False:
                resultado.append(t)
            else:
                grupos[_normalizar(t.texto)].append(t)

        for alvo, itens in grupos.items():
            aparicoes = [
                a
                for a in (
                    _aparicoes(
                        self._segundos_com_o_texto(alvo), self._tolerancia, duracao_ms
                    )
                    if alvo
                    else []
                )
                if trecho_ms is None or _sobreposicao(a, trecho_ms) > 0
            ]
            livres = list(aparicoes)
            for t in sorted(itens, key=lambda x: x.inicio_ms):
                if livres:
                    escolhida = min(livres, key=lambda a: _distancia(t, a))
                    livres.remove(escolhida)
                    resultado.append(_com_tempo(t, escolhida))
                elif not any(_distancia(t, a)[0] < 0 for a in aparicoes):
                    resultado.append(t.model_copy(update={"medido": False}))
                # senão, o item repete uma aparição que já tem dono
            molde = itens[0]
            resultado += [_extra(molde, a) for a in livres]
        resultado.sort(key=lambda t: (t.inicio_ms, t.fim_ms))
        return decupagem.model_copy(update={"textos_na_tela": resultado})


def medir_textos(
    decupagem: Decupagem,
    leitura: LeituraDaTela,
    *,
    limiar: float = LIMIAR_DE_SEMELHANCA_DO_OCR,
    tolerancia: int = TOLERANCIA_DE_QUADROS,
    trecho_ms: tuple[int, int] | None = None,
) -> Decupagem:
    """`MedicaoDosTextos.medir` de uma decupagem só."""
    return MedicaoDosTextos(leitura, limiar=limiar, tolerancia=tolerancia).medir(
        decupagem, trecho_ms
    )


def _com_tempo(texto: TextoNaTela, aparicao: _Aparicao) -> TextoNaTela:
    inicio, fim = aparicao
    mudanca: dict[str, object] = {"inicio_ms": inicio, "fim_ms": fim, "medido": True}
    # Só o item que veio do Gemini guarda o tempo dele; o já medido não tem tempo do modelo.
    if (
        texto.medido is None
        and texto.inicio_modelo_ms is None
        and aparicao != (texto.inicio_ms, texto.fim_ms)
    ):
        mudanca |= {"inicio_modelo_ms": texto.inicio_ms, "fim_modelo_ms": texto.fim_ms}
    return texto.model_copy(update=mudanca)


def _extra(molde: TextoNaTela, aparicao: _Aparicao) -> TextoNaTela:
    """Aparição que o Gemini não listou, com o tipo e o texto de um item dele."""
    inicio, fim = aparicao
    return molde.model_copy(
        update={
            "inicio_ms": inicio,
            "fim_ms": fim,
            "medido": True,
            "inicio_modelo_ms": None,
            "fim_modelo_ms": None,
        }
    )
