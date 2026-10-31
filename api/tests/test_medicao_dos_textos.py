"""A medição dos textos na tela com quadros fixos, sem nuvem."""

import json

from api.analise_por_janelas import analisar_video
from api.decupagem import Decupagem
from api.leitura_da_tela import Caixa, LeituraDaTela, LinhaLida, QuadroLido
from api.medicao_dos_textos import medir_textos
from api.tests.test_analise_por_janelas import (
    DURACAO_MS,
    URI,
    VIDEO,
    ModeloFalso,
    resposta,
)
from api.tests.test_escalonamento import decupagem

DURACAO = 120_000
TARJA = "DIA DO MEDICAMENTO BARATO ACESSE: ULTRAFARMA.COM"


def linha(texto: str, y: float = 0.5) -> LinhaLida:
    return LinhaLida(
        texto=texto,
        confianca=0.9,
        caixa=Caixa(x=0.1, y=y, largura=0.5, altura=0.05),
    )


def leitura(quadros: dict[int, list[LinhaLida]], total: int = 120) -> LeituraDaTela:
    return LeituraDaTela(
        modelo="falso",
        quadros=[
            QuadroLido(segundo=s, linhas=quadros.get(s, [])) for s in range(total)
        ],
    )


def com_textos(*textos: tuple[int, int, str]) -> Decupagem:
    dados = decupagem(("Ana", True)).model_dump()
    dados["video"]["duracao_ms"] = DURACAO
    dados["textos_na_tela"] = [
        {"inicio_ms": i, "fim_ms": f, "tipo": "tarja", "texto": t} for i, f, t in textos
    ]
    return Decupagem.model_validate(dados)


def tempos(d: Decupagem) -> list[tuple[int, int, bool | None]]:
    return [(t.inicio_ms, t.fim_ms, t.medido) for t in d.textos_na_tela]


def test_tarja_que_some_na_tela_preta_e_volta_sai_em_duas_aparicoes() -> None:
    quadros = {s: [linha(TARJA)] for s in [*range(3), *range(28, 85)]}
    # o Gemini cobriu a tela preta: 00:00–00:23
    d = com_textos((0, 23_000, TARJA))

    medido = medir_textos(d, leitura(quadros))

    assert tempos(medido) == [(0, 3_000, True), (28_000, 85_000, True)]
    primeiro, segundo = medido.textos_na_tela
    assert (primeiro.inicio_modelo_ms, primeiro.fim_modelo_ms) == (0, 23_000)
    assert segundo.inicio_modelo_ms is None


def test_falha_isolada_do_ocr_nao_parte_a_aparicao() -> None:
    quadros = {s: [linha(TARJA)] for s in range(10, 20) if s != 14}

    medido = medir_textos(com_textos((10_000, 20_000, TARJA)), leitura(quadros))

    assert tempos(medido) == [(10_000, 20_000, True)]


def test_falha_de_dois_quadros_parte_a_aparicao_com_a_tolerancia_padrao() -> None:
    quadros = {s: [linha(TARJA)] for s in range(10, 20) if s not in (14, 15)}

    medido = medir_textos(com_textos((10_000, 20_000, TARJA)), leitura(quadros))

    assert tempos(medido) == [(10_000, 14_000, True), (16_000, 20_000, True)]
    assert (
        medir_textos(
            com_textos((10_000, 20_000, TARJA)), leitura(quadros), tolerancia=2
        )
        .textos_na_tela[0]
        .fim_ms
        == 20_000
    )


def test_texto_que_o_ocr_nao_acha_fica_com_o_tempo_do_gemini_e_nao_medido() -> None:
    quadros = {s: [linha("OUTRA COISA")] for s in range(30)}

    medido = medir_textos(com_textos((5_000, 9_000, "QR PEQUENO")), leitura(quadros))

    assert tempos(medido) == [(5_000, 9_000, False)]


def test_tarja_de_duas_linhas_casa_com_o_texto_numa_linha_so() -> None:
    quadros = {
        s: [
            linha("ACESSE: ULTRAFARMA.COM", y=0.9),
            linha("DIA DO MEDICAMENTO BARATO", y=0.8),
        ]
        for s in range(28, 40)
    }

    medido = medir_textos(com_textos((0, 5_000, TARJA)), leitura(quadros))

    assert tempos(medido) == [(28_000, 40_000, True)]
    assert (
        medido.textos_na_tela[0].inicio_modelo_ms,
        medido.textos_na_tela[0].fim_modelo_ms,
    ) == (0, 5_000)


def test_acento_e_caixa_nao_atrapalham() -> None:
    quadros = {s: [linha("metro s. judas")] for s in range(24, 26)}

    medido = medir_textos(com_textos((0, 1_000, "METRÔ S. JUDAS")), leitura(quadros))

    assert tempos(medido) == [(24_000, 26_000, True)]


def test_o_tempo_do_gemini_escolhe_a_aparicao_quando_o_texto_repete() -> None:
    quadros = {s: [linha("OFERTA")] for s in [*range(10, 15), *range(50, 55)]}

    medido = medir_textos(
        com_textos((51_000, 53_000, "OFERTA"), (9_000, 12_000, "OFERTA")),
        leitura(quadros),
    )

    assert tempos(medido) == [(10_000, 15_000, True), (50_000, 55_000, True)]
    # o item que o Gemini deu perto de 51 s ficou com a segunda aparição
    assert medido.textos_na_tela[1].inicio_modelo_ms == 51_000


def test_aparicao_que_o_gemini_nao_listou_entra_com_o_item_dele() -> None:
    quadros = {s: [linha("OFERTA")] for s in [*range(10, 15), *range(50, 55)]}

    medido = medir_textos(com_textos((10_000, 15_000, "OFERTA")), leitura(quadros))

    assert tempos(medido) == [(10_000, 15_000, True), (50_000, 55_000, True)]


def test_o_fim_nao_passa_da_duracao() -> None:
    quadros = {s: [linha("OFERTA")] for s in range(115, 120)}

    medido = medir_textos(com_textos((115_000, 120_000, "OFERTA")), leitura(quadros))

    assert tempos(medido) == [(115_000, 120_000, True)]


def test_na_janela_o_texto_so_casa_com_aparicao_que_toca_o_trecho() -> None:
    # o OCR só acha OFERTA longe da janela: o item não vai para lá
    quadros = {s: [linha("OFERTA")] for s in range(10, 15)}

    medido = medir_textos(
        com_textos((100_000, 102_000, "OFERTA")),
        leitura(quadros),
        trecho_ms=(60_000, 120_000),
    )

    assert tempos(medido) == [(100_000, 102_000, False)]


def test_item_repetido_sem_aparicao_livre_fica_nao_medido() -> None:
    quadros = {s: [linha("OFERTA")] for s in [*range(10, 15), *range(50, 55)]}

    medido = medir_textos(
        com_textos(
            (10_000, 15_000, "OFERTA"),
            (50_000, 55_000, "OFERTA"),
            (90_000, 92_000, "OFERTA"),
        ),
        leitura(quadros),
    )

    assert tempos(medido) == [
        (10_000, 15_000, True),
        (50_000, 55_000, True),
        (90_000, 92_000, False),
    ]


def test_item_que_repete_uma_aparicao_ja_com_dono_sai() -> None:
    # o Gemini partiu em dois uma aparição só
    quadros = {s: [linha("OFERTA")] for s in range(10, 20)}

    medido = medir_textos(
        com_textos((10_000, 14_000, "OFERTA"), (15_000, 20_000, "OFERTA")),
        leitura(quadros),
    )

    assert tempos(medido) == [(10_000, 20_000, True)]


def test_medir_de_novo_nao_muda_o_que_ja_foi_medido() -> None:
    quadros = {s: [linha("OFERTA")] for s in [*range(10, 15), *range(50, 55)]}
    d = com_textos((0, 5_000, "OFERTA"), (100_000, 102_000, "SUMIU"))
    primeira = medir_textos(d, leitura(quadros))

    segunda = medir_textos(primeira, leitura(quadros))

    assert segunda == primeira
    assert tempos(segunda) == [
        (10_000, 15_000, True),
        (50_000, 55_000, True),
        (100_000, 102_000, False),
    ]
    assert [t.inicio_modelo_ms for t in segunda.textos_na_tela] == [0, None, None]


def resposta_com_texto(texto: str, inicio: str, fim: str) -> str:
    dados = json.loads(resposta())
    dados["textos_na_tela"] = [
        {"inicio": inicio, "fim": fim, "tipo": "gc", "texto": texto}
    ]
    return json.dumps(dados)


def test_analise_por_janelas_mede_os_textos_e_conta_o_nao_achado_como_duvida() -> None:
    quadros = {s: [linha("OFERTA")] for s in range(20, 30)}
    modelo = ModeloFalso(
        lambda inicio, _f: (
            resposta_com_texto("OFERTA", "00:00", "00:05")
            if inicio == 0
            else resposta_com_texto("SUMIU", "05:10", "05:12")
            if inicio == 290_000
            else resposta()
        )
    )

    d = analisar_video(
        modelo,
        video_uri=URI,
        job_id="j",
        video=VIDEO,
        leitura=leitura(quadros, total=DURACAO_MS // 1000),
        fracao_escalonada=0,
        dormir=lambda _s: None,
    )

    achados = {t.texto: t for t in d.textos_na_tela}
    assert (achados["OFERTA"].inicio_ms, achados["OFERTA"].fim_ms) == (20_000, 30_000)
    assert achados["OFERTA"].medido is True
    assert achados["SUMIU"].medido is False
    # a janela de SUMIU (e as outras com texto não achado) foi refeita: duas chamadas
    assert len(modelo.chamadas) > 30


def test_texto_que_o_ocr_so_acha_em_outra_janela_nao_some() -> None:
    # OFERTA só está nos quadros de 20 a 30 s, mas quem a lê é a janela de 05:00
    quadros = {s: [linha("OFERTA")] for s in range(20, 30)}
    modelo = ModeloFalso(
        lambda inicio, _f: (
            resposta_com_texto("OFERTA", "05:10", "05:12")
            if inicio == 290_000
            else resposta()
        )
    )

    d = analisar_video(
        modelo,
        video_uri=URI,
        job_id="j",
        video=VIDEO,
        leitura=leitura(quadros, total=DURACAO_MS // 1000),
        dormir=lambda _s: None,
    )

    assert tempos(d) == [(310_000, 312_000, False)]
