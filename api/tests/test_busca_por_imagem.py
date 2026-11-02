"""A busca por imagem (#270): a foto é entrada hostil e nunca é guardada."""

import io
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.rota_da_busca import LimitesDaImagem
from api.tests.test_busca import (
    AUTORIZACAO,
    EmbeddingDeTexto,
    cliente,
    job,
    plano,
)

ROTA = "/v1/busca/imagem"


def foto(formato: str = "PNG", tamanho: tuple[int, int] = (32, 24), **kw: Any) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", tamanho, (200, 30, 30)).save(saida, format=formato, **kw)
    return saida.getvalue()


def enviar(c: TestClient, dados: bytes, nome: str = "foto.jpg", **params: str) -> Any:
    return c.post(
        ROTA,
        files={"arquivo": (nome, dados, "image/jpeg")},
        params=params,
        headers=AUTORIZACAO,
    )


def com_planos(embedding: EmbeddingDeTexto, **kw: Any) -> tuple[TestClient, Any]:
    c, m = cliente(["consulta"], embedding_da_consulta=embedding, **kw)
    m.com(
        job("j1", programa="TV Fama"),
        plano("j1:plano:1", [1.0, 0.0], "rua escura"),
        plano("j1:plano:2", [0.0, 1.0], "estúdio"),
    )
    return c, m


def test_png_com_extensao_jpg_e_aceito_pelo_conteudo_e_acha_o_plano() -> None:
    embedding = EmbeddingDeTexto([1.0, 0.0])
    c, m = com_planos(embedding)

    r = enviar(c, foto("PNG"), nome="foto.jpg")

    assert r.status_code == 200
    corpo = r.json()
    assert corpo["entendida"]["visual"] is True
    assert [mo["inicio_ms"] for v in corpo["videos"] for mo in v["momentos"]] == [
        10_000
    ]
    # O modelo de texto não é chamado: não há consulta a entender.
    assert m.transporte.chamadas == []
    [vetor] = [c for c in m.indice.consultas if c.vetor_do_quadro]
    assert vetor.filtros.tipo == "plano" and vetor.texto is None


@pytest.mark.parametrize("formato", ["JPEG", "PNG"])
def test_jpeg_e_png_sao_aceitos(formato: str) -> None:
    c, _ = com_planos(EmbeddingDeTexto([1.0, 0.0]))
    assert enviar(c, foto(formato)).status_code == 200


def test_a_imagem_que_vai_ao_embedding_e_um_jpeg_novo_sem_metadados() -> None:
    exif = Image.Exif()
    exif[0x010F] = "Camera Secreta"
    original = foto("JPEG", exif=exif, icc_profile=b"perfil-falso" * 10)
    assert b"Camera Secreta" in original
    embedding = EmbeddingDeTexto([1.0, 0.0])
    c, _ = com_planos(embedding)

    assert enviar(c, original).status_code == 200

    [enviada] = embedding.imagens
    assert enviada != original
    assert b"Camera Secreta" not in enviada and b"perfil-falso" not in enviada
    with Image.open(io.BytesIO(enviada)) as lida:
        assert lida.format == "JPEG"
        assert not lida.getexif()
        assert "icc_profile" not in lida.info


@pytest.mark.parametrize(
    "dados",
    [
        foto("GIF"),
        foto("WEBP"),
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="9" height="9"/></svg>',
        foto("PNG")[:40],
        b"",
        b"nao e imagem",
    ],
    ids=["gif", "webp", "svg", "truncado", "vazio", "texto"],
)
def test_tipo_errado_ou_arquivo_quebrado_e_recusado_em_portugues(
    dados: bytes,
) -> None:
    embedding = EmbeddingDeTexto([1.0, 0.0])
    c, _ = com_planos(embedding)

    r = enviar(c, dados, nome="foto.png")

    assert r.status_code == 422
    assert r.json()["detail"] == "Envie uma imagem JPEG ou PNG válida"
    assert embedding.imagens == []


def test_imagem_acima_do_limite_de_bytes_e_recusada() -> None:
    c, _ = com_planos(
        EmbeddingDeTexto([1.0, 0.0]), limites_da_imagem=LimitesDaImagem(max_bytes=100)
    )
    r = enviar(c, foto("PNG", (64, 64), compress_level=0))
    assert r.status_code == 422
    assert r.json()["detail"] == "A imagem passa do tamanho máximo"


def test_imagem_acima_do_limite_de_pixels_e_recusada() -> None:
    c, _ = com_planos(
        EmbeddingDeTexto([1.0, 0.0]), limites_da_imagem=LimitesDaImagem(max_pixels=100)
    )
    r = enviar(c, foto("PNG", (20, 20)))
    assert r.status_code == 422
    assert r.json()["detail"] == "A imagem passa do tamanho máximo em pixels"


def test_os_filtros_de_programa_e_periodo_valem() -> None:
    c, m = com_planos(EmbeddingDeTexto([1.0, 0.0]))

    r = enviar(c, foto(), programa="Leo Dias", sem_periodo="true")
    assert r.status_code == 200 and r.json()["videos"] == []
    assert {x.filtros.programa for x in m.indice.consultas} == {"Leo Dias"}

    r = enviar(c, foto(), desde="2025-01-01", ate="2025-01-02")
    assert {x.filtros.exibido_desde.isoformat() for x in m.indice.consultas[1:]} == {
        "2025-01-01"
    }

    r = enviar(c, foto(), desde="2025-02-01", ate="2025-01-02")
    assert r.status_code == 422


def test_sem_decupagem_ver_responde_403_e_sem_login_401() -> None:
    c, _ = cliente([])
    assert enviar(c, foto()).status_code == 403
    r = c.post(ROTA, files={"arquivo": ("a.png", foto(), "image/png")})
    assert r.status_code == 401


def test_sem_embedding_ou_com_embedding_fora_responde_503() -> None:
    sem, _ = cliente(["consulta"])
    assert enviar(sem, foto()).status_code == 503
    fora, _ = com_planos(EmbeddingDeTexto(ConnectionError("x")))
    r = enviar(fora, foto())
    assert r.status_code == 503
    assert r.json()["detail"] == "A busca por imagem não está disponível agora"


def test_arquivo_ausente_responde_422() -> None:
    c, _ = com_planos(EmbeddingDeTexto([1.0, 0.0]))
    assert c.post(ROTA, headers=AUTORIZACAO).status_code == 422


def test_nada_e_gravado_nem_logado(caplog: pytest.LogCaptureFixture) -> None:
    c, m = com_planos(EmbeddingDeTexto([1.0, 0.0]))
    dados = foto("PNG", (48, 48))

    def estado() -> tuple[Any, ...]:
        a = m.armazenamento
        return (
            dict(a.quadros),
            dict(a.decupagens),
            list(a.pedidos),
            dict(m.jobs._jobs),
            m.indice.total(),
        )

    antes = estado()
    with caplog.at_level(logging.DEBUG):
        assert enviar(c, dados, nome="segredo-da-pauta.png").status_code == 200
        assert enviar(c, b"lixo", nome="segredo-da-pauta.png").status_code == 422

    assert estado() == antes
    assert "segredo-da-pauta" not in caplog.text
    assert dados[:16].hex() not in caplog.text


def test_a_busca_por_imagem_conta_no_limite_de_consultas() -> None:
    c, _ = com_planos(EmbeddingDeTexto([1.0, 0.0]), maximo_por_minuto=1)
    assert enviar(c, foto()).status_code == 200
    assert enviar(c, foto()).status_code == 429
