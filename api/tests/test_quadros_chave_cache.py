"""Cache de quadros por instante em `com_quadros_chave` (#548)."""

import io
from pathlib import Path

import pytest
from PIL import Image

from api.decupagem import Decupagem
from api.quadros_chave import com_quadros_chave


def _jpeg(cor: int) -> bytes:
    saida = io.BytesIO()
    Image.new("L", (8, 8), cor).save(saida, "JPEG")
    return saida.getvalue()


def _com_ffmpeg_falso(
    monkeypatch: pytest.MonkeyPatch, escuros: set[int], ausentes: set[int]
) -> list[list[int]]:
    """Troca o ffmpeg por um dublê e devolve os lotes de instantes pedidos a ele."""
    lotes: list[list[int]] = []

    def falsa(video: Path, instantes: list[int]) -> list[bytes | None]:
        lotes.append(list(instantes))
        return [
            None if t in ausentes else _jpeg(0 if t in escuros else 200)
            for t in instantes
        ]

    monkeypatch.setattr("api.quadros_chave.extrair_quadros_em_lote", falsa)
    return lotes


def _decupagem_com_meio_em(meio_ms: int, meia_largura_ms: int = 250) -> Decupagem:
    """Um plano, uma aparição e uma ocorrência de objeto, todos com o mesmo meio."""
    intervalo = {
        "inicio_ms": meio_ms - meia_largura_ms,
        "fim_ms": meio_ms + meia_largura_ms,
    }
    return Decupagem.model_validate(
        {
            "versao_esquema": "1.3",
            "video": {"sha256": "a" * 64, "duracao_ms": 6_000},
            "programa": {"resumo": "r", "blocos": []},
            "pautas": [],
            "pessoas": [
                {
                    "id": "pes01",
                    "nome": "Fulana",
                    "na_imagem": [{**intervalo, "evidencia": "rosto"}],
                    "citada_na_fala": [],
                    "citada_no_texto": [],
                }
            ],
            "objetos": [
                {
                    "id": "obj01",
                    "categoria": "calcado",
                    "tipo": "sandália",
                    "cor_base": ["vermelho"],
                    "ocorrencias": [intervalo],
                }
            ],
            "planos": [
                {
                    "id": "pla0",
                    "inicio_ms": 0,
                    "fim_ms": 2 * meio_ms,
                    "ambiente": "estúdio",
                    "plano_limpo": True,
                }
            ],
            "comerciais": [],
            "transcricao": [],
        }
    )


def test_o_mesmo_instante_pedido_por_plano_aparicao_e_objeto_chama_o_ffmpeg_uma_vez(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lotes = _com_ffmpeg_falso(monkeypatch, escuros=set(), ausentes=set())
    gravados: dict[str, bytes] = {}

    pronta = com_quadros_chave(
        tmp_path / "v.mp4", _decupagem_com_meio_em(1_000), gravados.__setitem__
    )

    assert lotes == [[1_000]]
    assert pronta.planos[0].quadro == "quadros/plano-0.jpg"
    assert pronta.planos[0].quadros == ["quadros/plano-0.jpg"]
    assert pronta.pessoas[0].na_imagem[0].quadro == "quadros/aparicao-0-0.jpg"
    assert pronta.objetos[0].quadro == "quadros/objeto-0.jpg"
    assert gravados == {
        "quadros/plano-0.jpg": _jpeg(200),
        "quadros/aparicao-0-0.jpg": _jpeg(200),
        "quadros/objeto-0.jpg": _jpeg(200),
    }


def test_escuro_e_lembrado_a_falha_nao_e_e_cada_rodada_vai_num_lote_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Meio em 3 s: escuro; +1 s (4 s) ausente; -1 s (2 s) claro. Plano, aparição e objeto
    # pedem o mesmo instante: um lote por rodada, sem repetir o instante dentro dele.
    lotes = _com_ffmpeg_falso(monkeypatch, escuros={3_000}, ausentes={4_000})
    gravados: dict[str, bytes] = {}

    pronta = com_quadros_chave(
        tmp_path / "v.mp4", _decupagem_com_meio_em(3_000, 2_000), gravados.__setitem__
    )

    # O ausente (4 s) ganha uma rodada extra antes de os momentos avançarem.
    assert lotes == [[3_000], [4_000], [4_000], [2_000]]
    assert pronta.planos[0].quadro == "quadros/plano-0.jpg"
    assert pronta.pessoas[0].na_imagem[0].quadro == "quadros/aparicao-0-0.jpg"
    assert pronta.objetos[0].quadro == "quadros/objeto-0.jpg"
    assert set(gravados.values()) == {_jpeg(200)}


def test_momentos_de_instantes_diferentes_vao_no_mesmo_lote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lotes = _com_ffmpeg_falso(monkeypatch, escuros=set(), ausentes=set())
    decupagem = _decupagem_com_meio_em(1_000)
    decupagem.pessoas[0].na_imagem[0].inicio_ms = 1_000
    decupagem.pessoas[0].na_imagem[0].fim_ms = 3_000  # meio em 2 s

    com_quadros_chave(tmp_path / "v.mp4", decupagem, lambda c, j: None)

    assert lotes == [[1_000, 2_000]]


def test_falha_passageira_do_instante_ganha_uma_rodada_extra_para_todos_os_momentos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Plano de 0 a 6 s; aparição e objeto de 2,75 a 3,25 s (sem desvio que caiba): os três
    # têm alvo em 3 s. O ffmpeg falha na 1ª vez (#548): sem rodada extra, aparição e objeto
    # ficariam sem quadro, e a main (um pedido por momento) os recuperava.
    lotes: list[list[int]] = []

    def falha_so_a_primeira(video: Path, instantes: list[int]) -> list[bytes | None]:
        lotes.append(list(instantes))
        return [None if len(lotes) == 1 else _jpeg(200) for _ in instantes]

    monkeypatch.setattr(
        "api.quadros_chave.extrair_quadros_em_lote", falha_so_a_primeira
    )
    decupagem = _decupagem_com_meio_em(3_000, 250)
    decupagem.planos[0].fim_ms = 6_000

    pronta = com_quadros_chave(tmp_path / "v.mp4", decupagem, lambda c, j: None)

    assert pronta.planos[0].quadro == "quadros/plano-0.jpg"
    assert pronta.pessoas[0].na_imagem[0].quadro == "quadros/aparicao-0-0.jpg"
    assert pronta.objetos[0].quadro == "quadros/objeto-0.jpg"
    assert lotes == [[3_000], [3_000]]
