"""A transcrição do Whisper na decupagem: falas, menções e correções do Gemini.

O Gemini recebe a transcrição como texto e devolve quem fala em cada trecho e as
correções que propõe. O código decide: uma correção só vale com as duas travas
(a palavra corrigida é parecida com a original e existe um texto da tela, já
registrado naquele momento, que a contém); as outras são descartadas e
registradas. O texto original do Whisper fica ao lado do corrigido.
"""

from collections.abc import Callable, Sequence
from difflib import SequenceMatcher

from api.comparador import normalizar
from api.decupagem import (
    CorrecaoDaTranscricao,
    CorrecaoDescartada,
    Decupagem,
    Fala,
    MencaoNaFala,
    MotivoDaRecusa,
)
from api.transcricao import Palavra, Transcricao

# Pelo "Corassa"/"Corazza" (0,71); "aí"/"Nelson" dá 0.
LIMIAR_DE_SEMELHANCA = 0.7
FOLGA_MS = 1_000  # o modelo escreve os tempos em segundos inteiros
_TAMANHO_MINIMO_DO_NOME = 3
NAO_IDENTIFICADO = "não identificado"


def _ms(segundos: float) -> int:
    return round(segundos * 1000)


def _palavras_em(
    palavras: Sequence[Palavra], inicio_ms: int, fim_ms: int
) -> list[Palavra]:
    return [
        p
        for p in palavras
        if inicio_ms - FOLGA_MS
        <= (_ms(p.inicio_s) + _ms(p.fim_s)) / 2
        <= fim_ms + FOLGA_MS
    ]


def _conferir(
    c: CorrecaoDaTranscricao,
    decupagem: Decupagem,
    transcricao: Transcricao,
    limiar: float,
) -> tuple[Palavra | None, MotivoDaRecusa | None]:
    """A palavra do Whisper que a correção troca e, se recusada, o motivo."""
    original = normalizar(c.original)
    achada = next(
        (
            p
            for p in _palavras_em(transcricao.palavras, c.inicio_ms, c.fim_ms)
            if normalizar(p.texto) == original
        ),
        None,
    )
    if achada is None:
        return None, "original_ausente"
    corrigida = normalizar(c.corrigida)
    prova = normalizar(c.prova)
    provas = [
        normalizar(t.texto)
        for t in decupagem.textos_na_tela
        if t.inicio_ms - FOLGA_MS <= c.fim_ms and c.inicio_ms <= t.fim_ms + FOLGA_MS
    ]
    if not any(corrigida in t and prova in t for t in provas):
        return achada, "sem_prova"
    if SequenceMatcher(None, original, corrigida).ratio() < limiar:
        return achada, "semelhanca_abaixo_do_limiar"
    return achada, None


def _falas(
    decupagem: Decupagem, palavras: list[Palavra], troca: dict[int, str]
) -> list[Fala]:
    """Uma fala por trecho do Gemini, com o texto do Whisper; o que sobra vira
    fala de quem não foi identificado."""

    def texto(ps: list[Palavra], corrigido: bool) -> str:
        return " ".join(troca.get(id(p), p.texto) if corrigido else p.texto for p in ps)

    falas: list[Fala] = []
    usadas: set[int] = set()
    for f in decupagem.transcricao:
        do_trecho = [
            p
            for p in palavras
            if id(p) not in usadas
            and f.inicio_ms <= (_ms(p.inicio_s) + _ms(p.fim_s)) / 2 <= f.fim_ms
        ]
        if not do_trecho:
            continue  # o modelo não transcreve: fala sem palavras é invenção
        usadas |= {id(p) for p in do_trecho}
        falas.append(_fala(f.locutor, do_trecho, texto, decupagem))
    sobra = [p for p in palavras if id(p) not in usadas]
    grupo: list[Palavra] = []
    for p in sobra:
        if grupo and p.inicio_s - grupo[-1].fim_s > 1:
            falas.append(_fala(NAO_IDENTIFICADO, grupo, texto, decupagem))
            grupo = []
        grupo.append(p)
    if grupo:
        falas.append(_fala(NAO_IDENTIFICADO, grupo, texto, decupagem))
    return sorted(falas, key=lambda f: (f.inicio_ms, f.fim_ms))


def _fala(
    locutor: str,
    ps: list[Palavra],
    texto: Callable[[list[Palavra], bool], str],
    decupagem: Decupagem,
) -> Fala:
    limite = decupagem.video.duracao_ms
    return Fala(
        locutor=locutor,
        texto=texto(ps, True),
        texto_original=texto(ps, False),
        inicio_ms=min(_ms(ps[0].inicio_s), limite),
        fim_ms=min(_ms(ps[-1].fim_s), limite),
    )


def _mencao(
    m: MencaoNaFala, nome: str, palavras: list[Palavra], troca: dict[int, str]
) -> MencaoNaFala:
    """Aperta a menção às palavras do nome, com o tempo exato do Whisper."""
    partes = {
        normalizar(parte)
        for parte in nome.split()
        if len(parte) >= _TAMANHO_MINIMO_DO_NOME
    }
    achadas = [
        p
        for p in _palavras_em(palavras, m.inicio_ms, m.fim_ms)
        if normalizar(troca.get(id(p), p.texto)).strip(".,;:!?") in partes
    ]
    if not achadas:
        return m
    inicio, fim = _ms(achadas[0].inicio_s), _ms(achadas[-1].fim_s)
    if (inicio, fim) == (m.inicio_ms, m.fim_ms):
        return m
    return m.model_copy(
        update={
            "inicio_ms": inicio,
            "fim_ms": fim,
            "inicio_modelo_ms": m.inicio_modelo_ms
            if m.inicio_modelo_ms is not None
            else m.inicio_ms,
            "fim_modelo_ms": m.fim_modelo_ms
            if m.fim_modelo_ms is not None
            else m.fim_ms,
        }
    )


def aplicar_transcricao(
    decupagem: Decupagem,
    transcricao: Transcricao | None,
    limiar: float = LIMIAR_DE_SEMELHANCA,
) -> Decupagem:
    """Põe a transcrição do Whisper no lugar das falas do modelo e confere as
    correções. Sem transcrição, as correções do modelo são ignoradas."""
    if transcricao is None:
        return decupagem.model_copy(update={"correcoes_da_transcricao": []})
    palavras = transcricao.palavras
    aceitas: list[CorrecaoDaTranscricao] = []
    descartadas: list[CorrecaoDescartada] = []
    troca: dict[int, str] = {}
    for c in decupagem.correcoes_da_transcricao:
        palavra, motivo = _conferir(c, decupagem, transcricao, limiar)
        if motivo is not None or palavra is None:
            descartadas.append(
                CorrecaoDescartada(
                    **c.model_dump(), motivo=motivo or "original_ausente"
                )
            )
            continue
        troca[id(palavra)] = c.corrigida
        aceitas.append(
            c.model_copy(
                update={
                    "original": palavra.texto,
                    "inicio_ms": _ms(palavra.inicio_s),
                    "fim_ms": min(_ms(palavra.fim_s), decupagem.video.duracao_ms),
                }
            )
        )
    pessoas = [
        p.model_copy(
            update={
                "citada_na_fala": [
                    _mencao(m, p.nome, palavras, troca) for m in p.citada_na_fala
                ]
            }
        )
        for p in decupagem.pessoas
    ]
    return decupagem.model_copy(
        update={
            "transcricao": _falas(decupagem, palavras, troca),
            "correcoes_da_transcricao": aceitas,
            "correcoes_descartadas": [*decupagem.correcoes_descartadas, *descartadas],
            "pessoas": pessoas,
        }
    )
