"""A transcrição do Whisper na decupagem: falas, menções e correções do Gemini.

O Gemini recebe a transcrição como texto e devolve quem fala em cada trecho e as
correções que propõe. O código decide: uma correção só vale com as duas travas
(a palavra corrigida é parecida com a original e existe um texto da tela, já
registrado naquele momento, que a contém); as outras são descartadas e
registradas. O texto original do Whisper fica ao lado do corrigido.
"""

from collections.abc import Sequence
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
_PONTUACAO = ".,;:!?…\"'()"
_CARACTERES_POR_FALA = 2000  # o limite de `Texto` em decupagem.py


def _ms(segundos: float) -> int:
    return round(segundos * 1000)


def _meio_ms(p: Palavra) -> float:
    return (_ms(p.inicio_s) + _ms(p.fim_s)) / 2


def _nucleo(texto: str) -> str:
    """A palavra normalizada, sem a pontuação que o Whisper cola nela."""
    return normalizar(texto).strip(_PONTUACAO)


def _trocar(palavra: str, corrigida: str) -> str:
    """Troca a palavra e mantém a pontuação em volta ("Corassa," → "Corazza,")."""
    inicio = len(palavra) - len(palavra.lstrip(_PONTUACAO))
    fim = len(palavra.rstrip(_PONTUACAO))
    return palavra[:inicio] + corrigida.strip(_PONTUACAO) + palavra[fim:]


def _palavras_em(
    palavras: Sequence[Palavra], inicio_ms: int, fim_ms: int
) -> list[Palavra]:
    return [
        p for p in palavras if inicio_ms - FOLGA_MS <= _meio_ms(p) <= fim_ms + FOLGA_MS
    ]


def _conferir(
    c: CorrecaoDaTranscricao,
    decupagem: Decupagem,
    transcricao: Transcricao,
    limiar: float,
) -> tuple[Palavra | None, MotivoDaRecusa | None]:
    """A palavra do Whisper que a correção troca e, se recusada, o motivo."""
    original = _nucleo(c.original)
    achada = next(
        (
            p
            for p in _palavras_em(transcricao.palavras, c.inicio_ms, c.fim_ms)
            if _nucleo(p.texto) == original
        ),
        None,
    )
    if achada is None:
        return None, "original_ausente"
    corrigida = _nucleo(c.corrigida)
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
    fala de quem não foi identificado.

    Cada palavra vai para o trecho mais perto do seu meio, com a folga dos
    segundos inteiros que o modelo escreve.
    """
    trechos = decupagem.transcricao
    do_trecho: list[list[Palavra]] = [[] for _ in trechos]
    sobra: list[Palavra] = []
    for p in palavras:
        meio = _meio_ms(p)
        distancias = [
            (max(f.inicio_ms - meio, meio - f.fim_ms, 0), i)
            for i, f in enumerate(trechos)
        ]
        perto = min(distancias, default=None)
        if perto is None or perto[0] > FOLGA_MS:
            sobra.append(p)
        else:
            do_trecho[perto[1]].append(p)
    limite = decupagem.video.duracao_ms
    falas: list[Fala] = []
    for f, ps in zip(trechos, do_trecho, strict=True):
        # trecho sem palavras fica de fora: o modelo não transcreve
        falas += _falas_do_grupo(f.locutor, ps, troca, limite)
    grupo: list[Palavra] = []
    for p in sobra:
        if grupo and p.inicio_s - grupo[-1].fim_s > 1:
            falas += _falas_do_grupo(NAO_IDENTIFICADO, grupo, troca, limite)
            grupo = []
        grupo.append(p)
    falas += _falas_do_grupo(NAO_IDENTIFICADO, grupo, troca, limite)
    return sorted(falas, key=lambda f: (f.inicio_ms, f.fim_ms))


def _falas_do_grupo(
    locutor: str, ps: list[Palavra], troca: dict[int, str], limite_ms: int
) -> list[Fala]:
    """As palavras de um locutor; um grupo longo demais vira mais de uma fala."""
    falas: list[Fala] = []
    atual: list[Palavra] = []
    tamanho = 0
    for p in ps:
        mais = len(troca.get(id(p), p.texto)) + 1
        if atual and tamanho + mais > _CARACTERES_POR_FALA:
            falas.append(_fala(locutor, atual, troca, limite_ms))
            atual, tamanho = [], 0
        atual.append(p)
        tamanho += mais
    if atual:
        falas.append(_fala(locutor, atual, troca, limite_ms))
    return falas


def _fala(
    locutor: str, ps: list[Palavra], troca: dict[int, str], limite_ms: int
) -> Fala:
    return Fala(
        locutor=locutor,
        texto=" ".join(troca.get(id(p), p.texto) for p in ps),
        texto_original=" ".join(p.texto for p in ps),
        inicio_ms=min(_ms(ps[0].inicio_s), limite_ms),
        fim_ms=min(_ms(ps[-1].fim_s), limite_ms),
    )


def _mencao(
    m: MencaoNaFala, nome: str, palavras: list[Palavra], troca: dict[int, str]
) -> MencaoNaFala:
    """Aperta a menção às palavras do nome, com o tempo exato do Whisper."""
    partes = {
        _nucleo(parte)
        for parte in nome.split()
        if len(parte) >= _TAMANHO_MINIMO_DO_NOME
    }
    achadas = [
        p
        for p in _palavras_em(palavras, m.inicio_ms, m.fim_ms)
        if _nucleo(troca.get(id(p), p.texto)) in partes
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
        troca[id(palavra)] = _trocar(palavra.texto, c.corrigida)
        limite = decupagem.video.duracao_ms
        aceitas.append(
            c.model_copy(
                update={
                    "original": palavra.texto,
                    "inicio_ms": min(_ms(palavra.inicio_s), limite),
                    "fim_ms": min(_ms(palavra.fim_s), limite),
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
