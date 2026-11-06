"""Vetor multimodal do quadro-chave de cada plano na indexação (#268)."""

import base64
from typing import Any

import pytest

from api import embedding_do_quadro
from api.agent_retrieval import ConfigDaBusca
from api.embedding_do_quadro import (
    MODELO_DO_EMBEDDING_DO_QUADRO,
    GeminiEmbedding,
    com_vetores_do_quadro,
    embedding_da_busca,
)
from api.indice_da_busca import Registro

JPEG = b"\xff\xd8quadro"


class EmbeddingFalso:
    def __init__(self, falha_em: str | None = None) -> None:
        self.chamadas: list[tuple[bytes, str]] = []
        self.falha_em = falha_em

    def vetor(self, jpeg: bytes, descricao: str) -> list[float]:
        if descricao == self.falha_em:
            raise ConnectionError("Vertex fora do ar")
        self.chamadas.append((jpeg, descricao))
        return [0.5, 0.5]


def _registro(tipo: str, id: str, **campos: Any) -> Registro:
    return Registro(id=id, tipo=tipo, job_id="j1", inicio_ms=0, fim_ms=1000, **campos)  # type: ignore[arg-type]


def _quadros(caminho: str) -> bytes:
    if caminho == "quadros/ausente.jpg":
        raise FileNotFoundError(caminho)
    return JPEG


def test_so_o_plano_leva_o_vetor_do_quadro() -> None:
    registros = [
        _registro("plano", "p0", quadro="quadros/p0.jpg", descricao="estúdio"),
        _registro("fala", "f0", quadro="quadros/p0.jpg", texto="oi"),
        _registro("objeto", "o0", quadro="quadros/o0.jpg", texto="vestido"),
    ]

    saida = com_vetores_do_quadro(registros, _quadros, EmbeddingFalso())

    assert [r.vetor_do_quadro for r in saida] == [[0.5, 0.5], None, None]


def test_o_quadro_vai_junto_com_a_descricao() -> None:
    embedding = EmbeddingFalso()

    com_vetores_do_quadro(
        [_registro("plano", "p0", quadro="quadros/p0.jpg", descricao="estúdio")],
        _quadros,
        embedding,
    )

    assert embedding.chamadas == [(JPEG, "estúdio")]


def test_plano_sem_quadro_segue_so_com_o_texto() -> None:
    embedding = EmbeddingFalso()

    [plano] = com_vetores_do_quadro(
        [_registro("plano", "p0", descricao="estúdio")], _quadros, embedding
    )

    assert plano.vetor_do_quadro is None
    assert embedding.chamadas == []


def test_quadro_que_nao_le_ou_embedding_que_falha_deixa_so_aquele_plano_sem_vetor() -> (
    None
):
    registros = [
        _registro("plano", "p0", quadro="quadros/ausente.jpg", descricao="a"),
        _registro("plano", "p1", quadro="quadros/p1.jpg", descricao="b"),
        _registro("plano", "p2", quadro="quadros/p2.jpg", descricao="c"),
    ]

    saida = com_vetores_do_quadro(registros, _quadros, EmbeddingFalso(falha_em="b"))

    assert [r.vetor_do_quadro for r in saida] == [None, None, [0.5, 0.5]]


def test_sem_embedding_os_registros_ficam_como_estao() -> None:
    registros = [_registro("plano", "p0", quadro="quadros/p0.jpg", descricao="a")]

    assert com_vetores_do_quadro(registros, _quadros, None) == registros


def test_o_pedido_ao_gemini_leva_texto_quadro_e_a_dimensao_da_colecao() -> None:
    pedidos: list[tuple[str, dict[str, Any]]] = []

    def transporte(url: str, corpo: dict[str, Any]) -> dict[str, Any]:
        pedidos.append((url, corpo))
        return {"embedding": {"values": [3.0, 4.0]}}

    vetor = GeminiEmbedding("proj", 2, transporte).vetor(JPEG, "estúdio")

    [(url, corpo)] = pedidos
    assert url == (
        "https://aiplatform.googleapis.com/v1/projects/proj/locations/global/"
        f"publishers/google/models/{MODELO_DO_EMBEDDING_DO_QUADRO}:embedContent"
    )
    partes = corpo["content"]["parts"]
    assert {"text": "estúdio"} in partes
    assert {
        "inlineData": {
            "mimeType": "image/jpeg",
            "data": base64.b64encode(JPEG).decode(),
        }
    } in partes
    assert corpo["embedContentConfig"] == {"outputDimensionality": 2}
    assert vetor == pytest.approx([0.6, 0.8])  # normalizado


def test_resposta_sem_a_dimensao_pedida_e_erro() -> None:
    def transporte(url: str, corpo: dict[str, Any]) -> dict[str, Any]:
        return {"embedding": {"values": [1.0, 2.0, 3.0]}}

    with pytest.raises(ValueError, match="dimensão"):
        GeminiEmbedding("proj", 2, transporte).vetor(JPEG, "x")


def _config(
    indice_do_quadro: str | None, indices_ligados: bool = True
) -> ConfigDaBusca:
    return ConfigDaBusca(
        projeto="proj",
        regiao="us-central1",
        colecao="c",
        indice_da_descricao="d",
        indice_do_quadro=indice_do_quadro,
        dimensao=256,
        indices_ligados=indices_ligados,
    )


def test_sem_busca_ou_sem_indice_do_quadro_nao_ha_embedding() -> None:
    assert embedding_da_busca(None) is None
    assert embedding_da_busca(_config(None)) is None


def test_sem_os_indices_ann_o_vetor_do_quadro_continua_calculado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # O dev roda sem índice ANN por custo (ADR 0006), e a busca por imagem segue.
    # O transporte falso evita pedir credencial do Google, que o CI não tem.
    monkeypatch.setattr(
        embedding_do_quadro, "transporte_http", lambda: lambda url, corpo: {}
    )
    assert embedding_da_busca(_config("q", indices_ligados=False)) is not None


def test_com_o_indice_do_quadro_o_embedding_usa_o_projeto_e_a_dimensao_da_busca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pedidos: list[tuple[str, dict[str, Any]]] = []

    def transporte(url: str, corpo: dict[str, Any]) -> dict[str, Any]:
        pedidos.append((url, corpo))
        return {"embedding": {"values": [1.0] * 256}}

    monkeypatch.setattr(embedding_do_quadro, "transporte_http", lambda: transporte)

    embedding = embedding_da_busca(_config("q"))
    assert embedding is not None
    embedding.vetor(JPEG, "estúdio")

    [(url, corpo)] = pedidos
    assert "/projects/proj/" in url
    assert corpo["embedContentConfig"] == {"outputDimensionality": 256}


def test_o_pedido_da_consulta_leva_so_o_texto() -> None:
    pedidos: list[dict[str, Any]] = []

    def transporte(url: str, corpo: dict[str, Any]) -> dict[str, Any]:
        pedidos.append(corpo)
        return {"embedding": {"values": [3.0, 4.0]}}

    vetor = GeminiEmbedding("proj", 2, transporte).vetor_do_texto("pista molhada")

    assert pedidos[0]["content"]["parts"] == [{"text": "pista molhada"}]
    assert pedidos[0]["embedContentConfig"] == {"outputDimensionality": 2}
    assert vetor == pytest.approx([0.6, 0.8])
