"""Pessoas sem nome olhadas pelo modelo forte (#110)."""

import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from api.decupagem import Decupagem
from api.gemini import ErroHttp
from api.modelo_forte import (
    ETAPA,
    MODELO_FORTE,
    agrupar,
    esquema_da_resposta,
    olhar_pessoas_sem_nome,
)
from api.quadros import FalhaNosQuadros
from api.quadros_das_pessoas import extrair_quadros, instantes_das_aparicoes
from api.tests.programas_de_teste import perfis_da_tv_fama
from api.tests.test_gemini import TransporteFalso
from api.tests.test_identificacao import decupagem, gc, pessoa, whisper

BARBA = "não identificado, homem de barba"
sem_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


def resposta(
    resultado: str,
    nome: str | None = None,
    prova: str | None = None,
    tempo: str | None = None,
) -> str:
    return json.dumps(
        {
            "resultado": resultado,
            "nome": nome,
            "prova": prova,
            "tempo_da_prova": tempo,
        }
    )


def quadros(instantes: Sequence[int]) -> list[bytes]:
    return [f"jpeg-{i}".encode() for i in instantes]


def olhar(d: Decupagem, transporte: TransporteFalso, **kw: Any) -> Decupagem:
    return olhar_pessoas_sem_nome(
        d,
        transporte=transporte,
        quadros_em=kw.pop("quadros_em", quadros),
        job_id="job-1",
        dormir=lambda _: None,
        **kw,
    )


def test_duas_aparicoes_da_mesma_pessoa_sem_nome_geram_uma_chamada() -> None:
    d = decupagem(
        [
            pessoa("pes01", BARBA, [(10_000, 20_000)], fontes_do_nome=[]),
            pessoa("pes02", "Não identificado: Homem de barba", [(50_000, 60_000)]),
        ]
    )
    transporte = TransporteFalso(resposta("nao_identificado"))

    olhar(d, transporte)

    assert len(transporte.chamadas) == 1


def test_a_pontuacao_depois_de_nao_identificado_nao_separa_a_pessoa() -> None:
    d = decupagem(
        [
            pessoa("pes01", "não identificado — repórter", [(0, 5_000)]),
            pessoa("pes02", "Não identificado, repórter.", [(10_000, 15_000)]),
        ]
    )

    assert [len(g.pessoas) for g in agrupar(d)] == [2]


def test_descricoes_diferentes_ou_sem_descricao_sao_pessoas_diferentes() -> None:
    d = decupagem(
        [
            pessoa("pes01", BARBA, [(10_000, 20_000)]),
            pessoa("pes02", "não identificado, mulher de óculos", [(10_000, 20_000)]),
            pessoa("pes03", "não identificado", [(30_000, 40_000)]),
            pessoa("pes04", "Não identificado", [(30_000, 40_000)]),
        ]
    )

    assert [len(g.pessoas) for g in agrupar(d)] == [1, 1, 1, 1]


def test_quem_ja_tem_nome_ou_nao_aparece_na_imagem_nao_vai_ao_modelo_forte() -> None:
    d = decupagem(
        [
            pessoa("pes01", "Leão Lobo", [(10_000, 20_000)]),
            pessoa("pes02", BARBA, []),
            pessoa("pes03", BARBA, [(10_000, 20_000)], origem="revisao"),
        ]
    )
    transporte = TransporteFalso()

    olhar(d, transporte)

    assert transporte.chamadas == []


def test_os_quadros_saem_das_aparicoes_mais_longas() -> None:
    d = decupagem(
        [
            pessoa(
                "pes01",
                BARBA,
                [(0, 2_000), (10_000, 30_000), (40_000, 48_000), (60_000, 61_000)],
            )
        ]
    )
    [pessoa_] = d.pessoas

    # as três mais longas: 20 s, 8 s e 2 s, no meio de cada uma
    assert instantes_das_aparicoes(pessoa_.na_imagem) == [1_000, 20_000, 44_000]


def test_uma_aparicao_so_da_dois_quadros_dela() -> None:
    d = decupagem([pessoa("pes01", BARBA, [(30_000, 60_000)])])

    assert instantes_das_aparicoes(d.pessoas[0].na_imagem) == [40_000, 50_000]


def test_a_mesma_aparicao_repetida_ainda_da_dois_quadros() -> None:
    d = decupagem(
        [
            pessoa("pes01", BARBA, [(30_000, 60_000)]),
            pessoa("pes02", BARBA, [(30_000, 60_000)]),
        ]
    )
    [grupo] = agrupar(d)

    aparicoes = [a for p in grupo.pessoas for a in p.na_imagem]
    assert instantes_das_aparicoes(aparicoes) == [40_000, 50_000]


def test_a_chamada_leva_os_quadros_o_modelo_forte_e_o_rotulo_de_custo() -> None:
    d = decupagem([pessoa("pes01", BARBA, [(10_000, 20_000), (40_000, 70_000)])])
    transporte = TransporteFalso(resposta("nao_identificado"))

    olhar(d, transporte, programa=None)

    [chamada] = transporte.chamadas
    assert chamada.modelo == MODELO_FORTE
    assert chamada.rotulos == {"job_id": "job-1", "etapa": ETAPA}
    assert chamada.imagens == (b"jpeg-15000", b"jpeg-55000")
    assert chamada.video_uri == ""
    assert chamada.modo == "standard"  # Standard, com cache (#402, #414)
    assert chamada.ferramentas == ()


def test_a_instrucao_traz_todas_as_pistas_do_video() -> None:
    d = decupagem(
        [pessoa("pes01", BARBA, [(10_000, 20_000)])],
        [gc("Leão Lobo, comentarista", 12_000, 18_000)],
    )
    transporte = TransporteFalso(resposta("nao_identificado"))

    olhar(
        d,
        transporte,
        programa="TV Fama",
        perfis=perfis_da_tv_fama(),
        transcricao=whisper(("Leãozinho!", 103.0), ("verdade", 104.0)),
    )

    texto = transporte.chamadas[0].instrucao
    assert "homem de barba" in texto  # a descrição do modelo barato
    assert "[01:43] Leãozinho! verdade" in texto  # a transcrição inteira
    assert "(gc) Leão Lobo, comentarista" in texto  # textos da tela e GCs
    assert "00:10–00:20" in texto  # as aparições
    assert "Leãozinho" in texto  # candidatos do perfil, com os apelidos
    assert "Nunca identifique pela memória" in texto


def test_nome_com_prova_conferida_e_confirmado() -> None:
    d = decupagem(
        [pessoa("pes01", BARBA, [(100_000, 110_000)], fontes_do_nome=[])],
        [gc("Leão Lobo", 101_000, 108_000)],
    )
    transporte = TransporteFalso(resposta("nome_com_prova", "Leão Lobo", "gc", "01:41"))

    [p] = olhar(d, transporte).pessoas

    assert (p.nome, p.estado_do_nome, p.origem, p.fontes_do_nome) == (
        "Leão Lobo",
        "confirmado",
        "modelo_forte",
        ["gc"],
    )


def test_nome_com_prova_pelo_apelido_na_fala_do_whisper_e_confirmado() -> None:
    d = decupagem([pessoa("pes01", BARBA, [(100_000, 110_000)], fontes_do_nome=[])])
    transporte = TransporteFalso(
        resposta("nome_com_prova", "Leão Lobo", "fala", "01:43")
    )

    [p] = olhar(
        d,
        transporte,
        programa="TV Fama",
        perfis=perfis_da_tv_fama(),
        transcricao=whisper(("Leãozinho!", 103.0)),
    ).pessoas

    assert (p.nome, p.estado_do_nome, p.fontes_do_nome) == (
        "Leão Lobo",
        "confirmado",
        ["fala"],
    )


def test_prova_que_o_modelo_cita_mas_o_codigo_nao_acha_vira_palpite() -> None:
    d = decupagem([pessoa("pes01", BARBA, [(100_000, 110_000)])])
    transporte = TransporteFalso(
        resposta("nome_com_prova", "Nelson Rubens", "fala", "01:43")
    )

    [p] = olhar(d, transporte, transcricao=whisper(("Olá", 103.0))).pessoas

    assert (p.nome, p.estado_do_nome, p.origem, p.fontes_do_nome) == (
        "Nelson Rubens",
        "palpite",
        "modelo_forte",
        [],
    )


def test_palpite_sem_prova_fica_como_palpite() -> None:
    d = decupagem([pessoa("pes01", BARBA, [(100_000, 110_000)])])
    transporte = TransporteFalso(resposta("palpite", "Leão Lobo"))

    [p] = olhar(d, transporte).pessoas

    assert (p.nome, p.estado_do_nome, p.fontes_do_nome) == ("Leão Lobo", "palpite", [])


def test_gc_de_outra_pessoa_sem_nome_no_mesmo_intervalo_nao_confirma() -> None:
    d = decupagem(
        [
            pessoa("pes01", BARBA, [(100_000, 110_000)]),
            pessoa("pes02", "não identificado, mulher de óculos", [(100_000, 110_000)]),
        ],
        [gc("Leão Lobo", 101_000, 108_000)],
    )
    transporte = TransporteFalso(
        resposta("nome_com_prova", "Leão Lobo", "gc", "01:41"),
        resposta("nao_identificado"),
    )

    barba, mulher = olhar(d, transporte).pessoas

    assert barba.estado_do_nome == "palpite"
    assert mulher.nome.startswith("não identificado")


def test_duas_pessoas_nomeadas_pelo_modelo_no_mesmo_intervalo_nao_se_confirmam() -> (
    None
):
    d = decupagem(
        [
            pessoa("pes01", BARBA, [(100_000, 112_000)]),
            pessoa("pes02", "não identificado, mulher de óculos", [(100_000, 110_000)]),
        ],
        [gc("Leão Lobo", 101_000, 108_000)],
    )
    transporte = TransporteFalso(
        resposta("nome_com_prova", "Leão Lobo", "gc", "01:41"),
        resposta("palpite", "Flávia Noronha"),
    )

    barba, mulher = olhar(d, transporte).pessoas

    assert (barba.estado_do_nome, mulher.estado_do_nome) == ("palpite", "palpite")


def test_entradas_da_mesma_pessoa_juntas_na_imagem_nao_se_bloqueiam() -> None:
    d = decupagem(
        [
            pessoa("pes01", BARBA, [(100_000, 110_000)]),
            pessoa("pes02", BARBA, [(105_000, 112_000)]),
        ],
        [gc("Leão Lobo", 106_000, 108_000)],
    )
    transporte = TransporteFalso(resposta("nome_com_prova", "Leão Lobo", "gc", "01:46"))

    r = olhar(d, transporte)

    assert len(transporte.chamadas) == 1
    assert [p.estado_do_nome for p in r.pessoas] == ["confirmado", "confirmado"]


def test_o_limite_por_video_e_respeitado_e_vale_a_de_mais_tempo_na_imagem() -> None:
    d = decupagem(
        [
            pessoa("pes01", "não identificado, a", [(0, 5_000)]),
            pessoa("pes02", "não identificado, b", [(0, 50_000)]),
            pessoa("pes03", "não identificado, c", [(0, 20_000)]),
        ]
    )
    transporte = TransporteFalso(
        resposta("palpite", "Fulano"), resposta("palpite", "Beltrano")
    )

    r = olhar(d, transporte, limite_de_pessoas=2)

    assert len(transporte.chamadas) == 2
    assert [p.nome for p in r.pessoas] == ["não identificado, a", "Fulano", "Beltrano"]


def test_limite_zero_nao_chama_o_modelo() -> None:
    d = decupagem([pessoa("pes01", BARBA, [(0, 5_000)])])
    transporte = TransporteFalso()

    assert olhar(d, transporte, limite_de_pessoas=0) == d
    assert transporte.chamadas == []


def test_nao_identificado_deixa_a_pessoa_como_esta() -> None:
    d = decupagem([pessoa("pes01", BARBA, [(0, 5_000)])])

    assert olhar(d, TransporteFalso(resposta("nao_identificado"))) == d


def test_falha_do_modelo_forte_deixa_a_pessoa_sem_nome_e_segue_com_as_outras() -> None:
    d = decupagem(
        [
            pessoa("pes01", "não identificado, a", [(0, 50_000)]),
            pessoa("pes02", "não identificado, b", [(0, 20_000)]),
        ]
    )
    transporte = TransporteFalso(ErroHttp(400), resposta("palpite", "Beltrano"))

    r = olhar(d, transporte)

    assert [p.nome for p in r.pessoas] == ["não identificado, a", "Beltrano"]


def test_falha_nos_quadros_deixa_a_pessoa_sem_nome_e_segue_com_as_outras() -> None:
    d = decupagem(
        [
            pessoa("pes01", "não identificado, a", [(0, 50_000)]),
            pessoa("pes02", "não identificado, b", [(0, 20_000)]),
        ]
    )
    falhas = iter([True, False])

    def quadros_que_falham(instantes: Sequence[int]) -> list[bytes]:
        if next(falhas):
            raise FalhaNosQuadros
        return quadros(instantes)

    transporte = TransporteFalso(resposta("palpite", "Beltrano"))

    r = olhar(d, transporte, quadros_em=quadros_que_falham)

    assert [p.nome for p in r.pessoas] == ["não identificado, a", "Beltrano"]
    assert len(transporte.chamadas) == 1


def test_resposta_fora_do_esquema_e_repetida_e_depois_desistida() -> None:
    d = decupagem([pessoa("pes01", BARBA, [(0, 5_000)])])
    sem_prova = resposta("nome_com_prova", "Leão Lobo")
    transporte = TransporteFalso(
        "lixo", sem_prova, resposta("palpite", "não identificado")
    )

    assert olhar(d, transporte) == d
    assert len(transporte.chamadas) == 3


def test_o_esquema_pedido_ao_modelo_tem_todo_campo_obrigatorio() -> None:
    esquema = esquema_da_resposta()

    assert set(esquema["required"]) == {"resultado", "nome", "prova", "tempo_da_prova"}


def _video(destino: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=60:size=320x240:rate=5",
            "-pix_fmt",
            "yuv420p",
            str(destino),
        ],
        check=True,
        capture_output=True,
    )
    return destino


@sem_ffmpeg
def test_os_quadros_extraidos_vem_dos_instantes_das_aparicoes_mais_longas(
    tmp_path: Path,
) -> None:
    video = _video(tmp_path / "limpa.mp4")
    d = decupagem(
        [pessoa("pes01", BARBA, [(0, 2_000), (10_000, 30_000), (40_000, 48_000)])]
    )
    transporte = TransporteFalso(resposta("nao_identificado"))

    olhar(d, transporte, quadros_em=lambda i: extrair_quadros(video, i))

    imagens = transporte.chamadas[0].imagens
    assert len(imagens) == 3
    assert all(i.startswith(b"\xff\xd8") and i.endswith(b"\xff\xd9") for i in imagens)
    assert imagens == tuple(extrair_quadros(video, [1_000, 20_000, 44_000]))
    # o testsrc muda a cada quadro: instantes diferentes dão quadros diferentes
    assert len(set(imagens)) == 3
    assert imagens[1] != extrair_quadros(video, [10_000])[0]
