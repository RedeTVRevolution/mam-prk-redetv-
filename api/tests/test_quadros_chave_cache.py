"""Cache de quadros por instante em `com_quadros_chave` (#548)."""

import io
from pathlib import Path

import pytest
from PIL import Image

from api.decupagem import Decupagem
from api.quadros import FalhaNosQuadros
from api.quadros_chave import com_quadros_chave


def _jpeg(cor: int) -> bytes:
    saida = io.BytesIO()
    Image.new("L", (8, 8), cor).save(saida, "JPEG")
    return saida.getvalue()


def _com_ffmpeg_falso(
    monkeypatch: pytest.MonkeyPatch, escuros: set[int], ausentes: set[int]
) -> list[int]:
    """Troca o ffmpeg por um dublê e devolve a lista dos instantes pedidos a ele."""
    pedidos: list[int] = []

    def falsa(video: Path, instantes: list[int]) -> list[bytes]:
        [t] = instantes
        pedidos.append(t)
        if t in ausentes:
            raise FalhaNosQuadros("depois do fim")
        return [_jpeg(0 if t in escuros else 200)]

    monkeypatch.setattr("api.quadros_chave.extrair_quadros", falsa)
    return pedidos


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
    pedidos = _com_ffmpeg_falso(monkeypatch, escuros=set(), ausentes=set())
    gravados: dict[str, bytes] = {}

    pronta = com_quadros_chave(
        tmp_path / "v.mp4", _decupagem_com_meio_em(1_000), gravados.__setitem__
    )

    assert pedidos == [1_000]
    assert pronta.planos[0].quadro == "quadros/plano-0.jpg"
    assert pronta.planos[0].quadros == ["quadros/plano-0.jpg"]
    assert pronta.pessoas[0].na_imagem[0].quadro == "quadros/aparicao-0-0.jpg"
    assert pronta.objetos[0].quadro == "quadros/objeto-0.jpg"
    assert gravados == {
        "quadros/plano-0.jpg": _jpeg(200),
        "quadros/aparicao-0-0.jpg": _jpeg(200),
        "quadros/objeto-0.jpg": _jpeg(200),
    }


def test_escuro_e_lembrado_a_falha_nao_e_e_a_saida_e_a_mesma(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Meio em 3 s: escuro; +1 s (4 s) ausente; -1 s (2 s) claro. O escuro e o claro entram no
    # cache; a falha não (pode ser timeout passageiro, #548): o 4 s é pedido de novo por
    # cada um dos dois momentos seguintes, em vez das seis chamadas a mais sem cache.
    pedidos = _com_ffmpeg_falso(monkeypatch, escuros={3_000}, ausentes={4_000})
    gravados: dict[str, bytes] = {}

    pronta = com_quadros_chave(
        tmp_path / "v.mp4", _decupagem_com_meio_em(3_000, 2_000), gravados.__setitem__
    )

    assert pedidos == [3_000, 4_000, 2_000, 4_000, 4_000]
    assert pronta.planos[0].quadro == "quadros/plano-0.jpg"
    assert pronta.pessoas[0].na_imagem[0].quadro == "quadros/aparicao-0-0.jpg"
    assert pronta.objetos[0].quadro == "quadros/objeto-0.jpg"
    assert set(gravados.values()) == {_jpeg(200)}
