"""Análise por janelas: o módulo dono do laço que decupa um vídeo longo.

Planeja as janelas, chama o Gemini uma vez por janela (com `startOffset` e
`endOffset`, contexto incluído), repete a janela que falha, consolida e aplica a
regra de tempos quando há cortes. Depois da consolidação, `identificar`
(`api/identificacao.py`) confere as provas do nome de cada pessoa. Com a leitura da tela (OCR), os tempos dos textos
na tela são os medidos nos quadros (`api/medicao_dos_textos.py`), por janela e de
novo depois da consolidação. O `Transporte` de `api/gemini.py` é o único
seam; `planejar_janelas`, `consolidar` e a regra de tempos são peças internas e
não são chamadas de fora. Uma janela que esgota as tentativas levanta
`AnaliseFalhou`: nunca sai Decupagem parcial.

Um vídeo de uma janela só (até 300 s) é uma chamada sobre o arquivo inteiro,
sem consolidar.

As janelas rodam até `max_paralelas` ao mesmo tempo. Com `janelas_do_job`, o estado
de cada janela e a Decupagem das concluídas ficam gravados: uma nova execução do
mesmo Job não chama o Gemini de novo para elas (nem refaz as que o escalonamento já
refez).
"""

import time
from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import AbstractContextManager, nullcontext
from functools import partial
from threading import Event

from api.catalogo import Catalogo
from api.consolidacao import consolidar
from api.decupagem import Decupagem, Video
from api.escalonamento import janelas_a_escalonar
from api.espera import sorteio_uniforme
from api.gemini import MODELO, AnaliseFalhou, Transporte, analisar
from api.identificacao import TOLERANCIA_DA_FALA_MS, candidatos_do_video, identificar
from api.janelas import (
    EstadoJanela,
    Janela,
    concluir,
    falhar,
    iniciar,
    planejar_janelas,
)
from api.leitura_da_tela import LeituraDaTela
from api.medicao_dos_textos import (
    LIMIAR_DE_SEMELHANCA_DO_OCR,
    TOLERANCIA_DE_QUADROS,
    MedicaoDosTextos,
)
from api.progresso_das_janelas import JanelaGravada, JanelasDoJob
from api.tempos import aplicar_regra_de_tempos
from api.transcricao import Transcricao
from api.transcricao_na_analise import LIMIAR_DE_SEMELHANCA


def _em_paralelo[T](tarefas: Sequence[Callable[[], T]], maximo: int) -> list[T]:
    """Roda as tarefas, no máximo `maximo` ao mesmo tempo; devolve os resultados na
    ordem. Depois da primeira falha, as que ainda não começaram não começam."""
    falhou = Event()

    def rodar(tarefa: Callable[[], T]) -> T:
        if falhou.is_set():
            raise CancelledError
        try:
            return tarefa()
        except BaseException:
            falhou.set()
            raise

    with ThreadPoolExecutor(max_workers=maximo) as pool:
        futuros = [pool.submit(rodar, t) for t in tarefas]
        erros = [f.exception() for f in futuros]
    # A falha de verdade é a primeira que não é um cancelamento.
    for erro in erros:
        if erro and not isinstance(erro, CancelledError):
            raise erro
    return [f.result() for f in futuros]


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
    leitura: LeituraDaTela | None = None,
    max_paralelas: int = 1,
    janelas_do_job: JanelasDoJob | None = None,
    limiar_do_ocr: float = LIMIAR_DE_SEMELHANCA_DO_OCR,
    tolerancia_do_ocr: int = TOLERANCIA_DE_QUADROS,
    limiar_de_semelhanca: float = LIMIAR_DE_SEMELHANCA,
    catalogo: Catalogo | None = None,
    tolerancia_da_fala_ms: int = TOLERANCIA_DA_FALA_MS,
    modelo: str = MODELO,
    etapa_de_custo: str | None = None,
    etapa: Callable[[str], AbstractContextManager[None]] = lambda _nome: nullcontext(),
    dormir: Callable[[float], None] = time.sleep,
    sortear: Callable[[float], float] = sorteio_uniforme,
    relogio: Callable[[], float] = time.monotonic,
) -> Decupagem:
    """Decupa o vídeo inteiro; levanta `AnaliseFalhou` se uma janela esgotar as tentativas.

    `fracao_escalonada` `None` desliga o escalonamento inteiro (motivos `duvida`
    e `amostra`); a entrada fica aqui, e o piloto escolhe a fração.

    `modelo` e `etapa_de_custo` (o rótulo de custo) são da passada de comparação
    (`api/passadas.py`); `etapa(nome)` envolve `janelas`, `consolidacao` e
    `identificacao`, para ela medir o tempo de cada uma.
    """
    if max_paralelas < 1:
        raise ValueError(f"janelas em paralelo: {max_paralelas}")
    janelas = planejar_janelas(video.duracao_ms)

    medicao = (
        MedicaoDosTextos(leitura, limiar=limiar_do_ocr, tolerancia=tolerancia_do_ocr)
        if leitura
        else None
    )

    def medir(decupagem: Decupagem, trecho_ms: tuple[int, int] | None) -> Decupagem:
        return medicao.medir(decupagem, trecho_ms) if medicao else decupagem

    def identificar_pessoas(decupagem: Decupagem) -> Decupagem:
        return identificar(
            decupagem,
            candidatos=candidatos_do_video(programa, catalogo),
            transcricao=transcricao,
            catalogo=catalogo,
            tolerancia_ms=tolerancia_da_fala_ms,
        )

    def passo(trecho_ms: tuple[int, int] | None) -> Decupagem:
        # Cada janela já sai medida: o texto que o OCR não achou é dúvida do escalonamento.
        return medir(chamar(trecho_ms), trecho_ms)

    def chamar(trecho_ms: tuple[int, int] | None) -> Decupagem:
        return analisar(
            transporte,
            video_uri=video_uri,
            job_id=job_id,
            video=video,
            programa=programa,
            trecho_ms=trecho_ms,
            cortes_ms=cortes_ms,
            modelo=modelo,
            etapa_de_custo=etapa_de_custo,
            transcricao=transcricao
            and transcricao.recortar(*(trecho_ms or (0, video.duracao_ms))),
            limiar_de_semelhanca=limiar_de_semelhanca,
            dormir=dormir,
            sortear=sortear,
            relogio=relogio,
        )

    if len(janelas) <= 1:
        with etapa("janelas"):
            unica = aplicar_regra_de_tempos(passo(None), cortes_ms)
        with etapa("identificacao"):
            return identificar_pessoas(unica)

    gravadas = janelas_do_job.ler(job_id) if janelas_do_job else {}

    def gravar(
        estado: EstadoJanela,
        decupagem: Decupagem | None = None,
        refeita: bool = False,
    ) -> None:
        if janelas_do_job:
            janelas_do_job.gravar(job_id, JanelaGravada.de(estado, decupagem, refeita))

    def decupar(janela: Janela, primeira: Decupagem | None = None) -> Decupagem:
        """Sem `primeira`, a primeira passada; com ela, o escalonamento, que mantém a
        Decupagem da primeira passada gravada até concluir: se o processo cair no meio,
        a retomada não refaz a primeira passada."""
        escalonando = primeira is not None
        guardada = gravadas.get(janela.indice)
        if not escalonando and guardada and guardada.decupagem:
            return guardada.decupagem
        # A tentativa interrompida da mesma passada retoma a contagem; a passada que
        # ainda não começou começa do zero.
        retoma = (
            guardada is not None
            and guardada.situacao != "concluida"
            and (guardada.decupagem is not None) == escalonando
        )
        estado = (
            guardada.estado
            if guardada and retoma
            else EstadoJanela(janela.indice, "pendente", 0, None)
        )
        while True:
            estado = iniciar(estado)
            gravar(estado, primeira)
            if estado.situacao == "falhou":
                raise AnaliseFalhou(estado.erro or "análise falhou")
            try:
                decupagem = passo((janela.inicio_contexto_ms, janela.fim_contexto_ms))
            except AnaliseFalhou as e:
                estado = falhar(estado, str(e) or "análise falhou")
                gravar(estado, primeira)
                if estado.situacao == "falhou":
                    raise
                continue
            gravar(concluir(estado), decupagem, refeita=escalonando)
            return decupagem

    def decupar_em_paralelo(
        indices: Sequence[int], escalonar: bool = False
    ) -> dict[int, Decupagem]:
        tarefas = [
            partial(decupar, janelas[i], resultados[i] if escalonar else None)
            for i in indices
        ]
        return dict(zip(indices, _em_paralelo(tarefas, max_paralelas), strict=True))

    with etapa("janelas"):
        resultados = decupar_em_paralelo([j.indice for j in janelas])
        if fracao_escalonada is not None:
            a_refazer = [
                indice
                for indice in janelas_a_escalonar(job_id, resultados, fracao_escalonada)
                if not (indice in gravadas and gravadas[indice].refeita)
            ]
            resultados.update(decupar_em_paralelo(a_refazer, escalonar=True))
    with etapa("consolidacao"):
        consolidada = medir(
            consolidar(
                video, [(j, resultados[j.indice]) for j in janelas], list(cortes_ms)
            ),
            None,
        )
    with etapa("identificacao"):
        return identificar_pessoas(consolidada)
