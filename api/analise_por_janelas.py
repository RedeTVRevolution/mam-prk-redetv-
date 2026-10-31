"""Análise por janelas: o módulo dono do laço que decupa um vídeo longo.

Planeja as janelas, chama o Gemini uma vez por janela (com `startOffset` e
`endOffset`, contexto incluído), repete a janela que falha, consolida e aplica a
regra de tempos quando há cortes. O `Transporte` de `api/gemini.py` é o único
seam; `planejar_janelas`, `consolidar` e a regra de tempos são peças internas e
não são chamadas de fora. Uma janela que esgota as tentativas levanta
`AnaliseFalhou`: nunca sai Decupagem parcial.

Um vídeo de uma janela só (até 300 s) é uma chamada sobre o arquivo inteiro,
sem consolidar. As janelas rodam uma depois da outra; o paralelismo e a
retomada são do #127.
"""

import time
from collections.abc import Callable, Sequence

from api.consolidacao import consolidar
from api.decupagem import Decupagem, Video
from api.escalonamento import janelas_a_escalonar
from api.espera import sorteio_uniforme
from api.gemini import AnaliseFalhou, Transporte, analisar
from api.janelas import (
    EstadoJanela,
    Janela,
    falhar,
    iniciar,
    planejar_janelas,
)
from api.tempos import aplicar_regra_de_tempos
from api.transcricao import Transcricao
from api.transcricao_na_analise import LIMIAR_DE_SEMELHANCA


def analisar_video(
    transporte: Transporte,
    *,
    video_uri: str,
    job_id: str,
    video: Video,
    programa: str | None = None,
    cortes_ms: Sequence[int] = (),
    fracao_escalonada: float | None = None,
    transcricao: Transcricao | None = None,
    limiar_de_semelhanca: float = LIMIAR_DE_SEMELHANCA,
    dormir: Callable[[float], None] = time.sleep,
    sortear: Callable[[float], float] = sorteio_uniforme,
    relogio: Callable[[], float] = time.monotonic,
) -> Decupagem:
    """Decupa o vídeo inteiro; levanta `AnaliseFalhou` se uma janela esgotar as tentativas.

    `fracao_escalonada` `None` desliga o escalonamento inteiro (motivos `duvida`
    e `amostra`); a entrada fica aqui, e o piloto escolhe a fração.
    """
    janelas = planejar_janelas(video.duracao_ms)

    def passo(trecho_ms: tuple[int, int] | None) -> Decupagem:
        return analisar(
            transporte,
            video_uri=video_uri,
            job_id=job_id,
            video=video,
            programa=programa,
            trecho_ms=trecho_ms,
            transcricao=transcricao
            and transcricao.recortar(*(trecho_ms or (0, video.duracao_ms))),
            limiar_de_semelhanca=limiar_de_semelhanca,
            dormir=dormir,
            sortear=sortear,
            relogio=relogio,
        )

    if len(janelas) <= 1:
        return aplicar_regra_de_tempos(passo(None), cortes_ms)

    def decupar(janela: Janela) -> Decupagem:
        estado = EstadoJanela(janela.indice, "pendente", 0, None)
        while True:
            estado = iniciar(estado)
            try:
                decupagem = passo((janela.inicio_contexto_ms, janela.fim_contexto_ms))
            except AnaliseFalhou as e:
                estado = falhar(estado, str(e) or "análise falhou")
                if estado.situacao == "falhou":
                    raise
                continue
            return decupagem

    resultados = {j.indice: decupar(j) for j in janelas}
    if fracao_escalonada is not None:
        for indice in janelas_a_escalonar(job_id, resultados, fracao_escalonada):
            resultados[indice] = decupar(janelas[indice])
    return consolidar(
        video, [(j, resultados[j.indice]) for j in janelas], list(cortes_ms)
    )
