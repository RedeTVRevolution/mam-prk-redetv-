"""A transcrição do Whisper na análise: instrução, falas, menções e correções.

Tudo pelo `analisar_video` com um transporte falso; o modelo simulado devolve
respostas em MM:SS como a Vertex.
"""

import json
import re
from typing import Any

from api.analise_por_janelas import analisar_video
from api.decupagem import Decupagem, Video
from api.gemini import Chamada
from api.tests.test_analise_por_janelas import DURACAO_MS as DURACAO_LONGA_MS
from api.tests.test_analise_por_janelas import ModeloFalso, mm_ss
from api.transcricao import Palavra, Transcricao

VIDEO = Video(sha256="d" * 64, duracao_ms=60_000)
URI = "gs://aceitos/j/proxy.mp4"


def palavras(*itens: tuple[str, float, float]) -> list[Palavra]:
    return [Palavra(texto=t, inicio_s=i, fim_s=f) for t, i, f in itens]


def transcricao(*itens: tuple[str, float, float]) -> Transcricao:
    return Transcricao(modelo="m", idioma="pt", palavras=palavras(*itens))


def modelo_responde(**campos: Any) -> str:
    base: dict[str, Any] = {
        "programa": {"resumo": "", "blocos": []},
        "pautas": [],
        "pessoas": [],
        "planos": [],
        "comerciais": [],
        "transcricao": [],
        "textos_na_tela": [],
        "correcoes_da_transcricao": [],
    }
    return json.dumps({**base, **campos})


def t(inicio_s: int, fim_s: int) -> dict[str, str]:
    return {"inicio": mm_ss(inicio_s * 1000), "fim": mm_ss(fim_s * 1000)}


def gc(texto: str, inicio_s: int, fim_s: int) -> dict[str, Any]:
    return {"tipo": "gc", "texto": texto, **t(inicio_s, fim_s)}


def correcao(
    original: str, corrigida: str, prova: str, inicio_s: int = 10, fim_s: int = 12
) -> dict[str, Any]:
    return {
        "original": original,
        "corrigida": corrigida,
        "prova": prova,
        **t(inicio_s, fim_s),
    }


FALAS = transcricao(
    ("A", 10.0, 10.2),
    ("Corassa", 10.3, 10.9),
    ("disse", 11.0, 11.4),
    ("sim", 11.5, 11.9),
)


def decupar(resposta: str, trans: Transcricao | None = FALAS) -> Decupagem:
    modelo = ModeloFalso(lambda _i, _f: resposta)
    return analisar_video(
        _SemTrecho(modelo),
        video_uri=URI,
        job_id="j",
        video=VIDEO,
        transcricao=trans,
        dormir=lambda _s: None,
    )


class _SemTrecho:
    """O vídeo curto é uma chamada sem trecho; o `ModeloFalso` exige um."""

    def __init__(self, modelo: ModeloFalso) -> None:
        self.modelo = modelo
        self.chamadas: list[Chamada] = []

    def gerar(self, chamada: Chamada) -> str:
        self.chamadas.append(chamada)
        return self.modelo.por_trecho(0, 0)  # type: ignore[return-value]


def test_corassa_para_corazza_passa_com_o_gc_da_andrea_corazza() -> None:
    d = decupar(
        modelo_responde(
            textos_na_tela=[gc("Andréa Corazza", 8, 20)],
            correcoes_da_transcricao=[correcao("Corassa", "Corazza", "Andréa Corazza")],
        )
    )

    [c] = d.correcoes_da_transcricao
    assert (c.original, c.corrigida, c.prova) == (
        "Corassa",
        "Corazza",
        "Andréa Corazza",
    )
    assert (c.inicio_ms, c.fim_ms) == (10_300, 10_900)  # o tempo da palavra
    assert d.correcoes_descartadas == []


def test_ai_para_nelson_e_recusada_mesmo_com_um_gc_que_diz_nelson() -> None:
    trans = transcricao(("aí", 10.0, 10.3), ("sim", 10.4, 10.8))
    d = decupar(
        modelo_responde(
            textos_na_tela=[gc("Nelson Leão", 8, 20)],
            correcoes_da_transcricao=[correcao("aí", "Nelson", "Nelson Leão")],
        ),
        trans,
    )

    assert d.correcoes_da_transcricao == []
    [r] = d.correcoes_descartadas
    assert (r.original, r.corrigida) == ("aí", "Nelson")
    assert r.motivo == "semelhanca_abaixo_do_limiar"
    assert "Nelson" not in d.transcricao[0].texto


def test_correcao_sem_texto_da_tela_que_a_prove_e_descartada_e_registrada() -> None:
    d = decupar(
        modelo_responde(
            textos_na_tela=[gc("Andréa Corazza", 30, 40)],  # fora daquele momento
            correcoes_da_transcricao=[correcao("Corassa", "Corazza", "Andréa Corazza")],
        )
    )

    assert d.correcoes_da_transcricao == []
    assert [r.motivo for r in d.correcoes_descartadas] == ["sem_prova"]
    assert "Corassa" in d.transcricao[0].texto


def test_correcao_de_palavra_que_o_whisper_nao_disse_e_descartada() -> None:
    d = decupar(
        modelo_responde(
            textos_na_tela=[gc("Andréa Corazza", 8, 20)],
            correcoes_da_transcricao=[correcao("Corasa", "Corazza", "Andréa Corazza")],
        )
    )

    assert [r.motivo for r in d.correcoes_descartadas] == ["original_ausente"]


def test_o_limiar_e_configuravel() -> None:
    modelo = ModeloFalso(
        lambda _i, _f: modelo_responde(
            textos_na_tela=[gc("Andréa Corazza", 8, 20)],
            correcoes_da_transcricao=[correcao("Corassa", "Corazza", "Andréa Corazza")],
        )
    )
    d = analisar_video(
        _SemTrecho(modelo),
        video_uri=URI,
        job_id="j",
        video=VIDEO,
        transcricao=FALAS,
        limiar_de_semelhanca=0.99,
        dormir=lambda _s: None,
    )

    assert [r.motivo for r in d.correcoes_descartadas] == [
        "semelhanca_abaixo_do_limiar"
    ]


def test_falas_vem_do_whisper_com_o_texto_corrigido_e_o_original() -> None:
    d = decupar(
        modelo_responde(
            transcricao=[{"locutor": "Ana", "texto": "inventado", **t(10, 12)}],
            textos_na_tela=[gc("Andréa Corazza", 8, 20)],
            correcoes_da_transcricao=[correcao("Corassa", "Corazza", "Andréa Corazza")],
        )
    )

    [fala] = d.transcricao
    assert fala.locutor == "Ana"
    assert fala.texto == "A Corazza disse sim"
    assert fala.texto_original == "A Corassa disse sim"


def test_fala_do_whisper_que_o_modelo_nao_atribuiu_nao_se_perde() -> None:
    d = decupar(modelo_responde())

    [fala] = d.transcricao
    assert fala.locutor == "não identificado"
    assert fala.texto == "A Corassa disse sim"


def test_mencao_na_fala_ganha_o_tempo_exato_das_palavras() -> None:
    pessoa = {
        "id": "p1",
        "nome": "Andréa Corazza",
        "fontes_do_nome": ["fala"],
        "na_imagem": [],
        "citada_na_fala": [t(10, 12)],
        "citada_no_texto": [],
    }
    d = decupar(
        modelo_responde(
            pessoas=[pessoa],
            textos_na_tela=[gc("Andréa Corazza", 8, 20)],
            correcoes_da_transcricao=[correcao("Corassa", "Corazza", "Andréa Corazza")],
        )
    )

    [m] = d.pessoas[0].citada_na_fala
    assert (m.inicio_ms, m.fim_ms) == (10_300, 10_900)
    assert (m.inicio_modelo_ms, m.fim_modelo_ms) == (10_000, 12_000)


def test_sem_transcricao_nada_muda_e_as_correcoes_do_modelo_sao_ignoradas() -> None:
    d = decupar(
        modelo_responde(
            transcricao=[{"locutor": "Ana", "texto": "fala do modelo", **t(10, 12)}],
            correcoes_da_transcricao=[correcao("Corassa", "Corazza", "x")],
        ),
        None,
    )

    assert d.transcricao[0].texto == "fala do modelo"
    assert d.transcricao[0].texto_original is None
    assert d.correcoes_da_transcricao == d.correcoes_descartadas == []


def test_a_instrucao_traz_a_transcricao_e_nao_pede_para_transcrever() -> None:
    modelo = ModeloFalso(lambda _i, _f: modelo_responde())
    ponte = _SemTrecho(modelo)
    analisar_video(
        ponte, video_uri=URI, job_id="j", video=VIDEO, transcricao=FALAS,
        dormir=lambda _s: None,
    )  # fmt: skip

    instrucao = ponte.chamadas[0].instrucao
    assert "A Corassa disse sim" in instrucao
    assert "00:10" in instrucao
    assert "Transcreva" not in instrucao


def test_cada_janela_recebe_so_o_trecho_da_transcricao_que_cabe_nela() -> None:
    # uma palavra no meio de cada núcleo de 300 s
    todas = transcricao(
        *[(f"palavra{k}", k * 300 + 150.0, k * 300 + 150.5) for k in range(30)]
    )
    modelo = ModeloFalso(lambda _i, _f: modelo_responde())

    analisar_video(
        modelo,
        video_uri=URI,
        job_id="j",
        video=Video(sha256="c" * 64, duracao_ms=DURACAO_LONGA_MS),
        transcricao=todas,
        dormir=lambda _s: None,
    )

    for chamada in modelo.chamadas:
        assert chamada.trecho_ms is not None
        k = chamada.trecho_ms[0] // 300_000 + (1 if chamada.trecho_ms[0] else 0)
        assert set(re.findall(r"palavra\d+", chamada.instrucao)) == {f"palavra{k}"}


def test_correcao_mantem_a_pontuacao_que_o_whisper_cola_na_palavra() -> None:
    trans = transcricao(
        ("A", 10.0, 10.2), ("Corassa,", 10.3, 10.9), ("sim", 11.0, 11.4)
    )
    d = decupar(
        modelo_responde(
            textos_na_tela=[gc("Andréa Corazza", 8, 20)],
            correcoes_da_transcricao=[correcao("Corassa", "Corazza", "Andréa Corazza")],
        ),
        trans,
    )

    [c] = d.correcoes_da_transcricao
    assert c.original == "Corassa,"
    assert d.transcricao[0].texto == "A Corazza, sim"
    assert d.transcricao[0].texto_original == "A Corassa, sim"


def test_palavra_logo_depois_do_fim_em_segundos_fica_com_o_trecho() -> None:
    trans = transcricao(("A", 10.0, 10.2), ("sim", 12.1, 12.5))
    d = decupar(
        modelo_responde(
            transcricao=[{"locutor": "Ana", "texto": "", **t(10, 12)}],
        ),
        trans,
    )

    [fala] = d.transcricao
    assert (fala.locutor, fala.texto) == ("Ana", "A sim")


def test_cada_palavra_vai_para_o_trecho_mais_perto() -> None:
    trans = transcricao(("um", 10.0, 10.4), ("dois", 11.6, 12.0))
    d = decupar(
        modelo_responde(
            transcricao=[
                {"locutor": "Ana", "texto": "", **t(10, 11)},
                {"locutor": "Beto", "texto": "", **t(12, 13)},
            ],
        ),
        trans,
    )

    assert [(f.locutor, f.texto) for f in d.transcricao] == [
        ("Ana", "um"),
        ("Beto", "dois"),
    ]


def test_fala_longa_demais_vira_mais_de_uma() -> None:
    trans = transcricao(*[("palavra", k * 0.1, k * 0.1 + 0.05) for k in range(400)])
    d = decupar(
        modelo_responde(transcricao=[{"locutor": "Ana", "texto": "", **t(0, 40)}]),
        trans,
    )

    assert len(d.transcricao) == 2
    assert all(f.locutor == "Ana" and len(f.texto) <= 2000 for f in d.transcricao)
    assert sum(len(f.texto.split()) for f in d.transcricao) == 400
