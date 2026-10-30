import json
from pathlib import Path
from typing import Any

import pytest

from api.cassete import CASSETE, gravar
from api.decupagem import Video
from api.gemini import MODELO, analisar
from api.tests.test_gemini import BOA, VIDEO, VIDEO_CONFIAVEL, TransporteFalso


def _cassete() -> dict[str, Any]:
    if not CASSETE.exists():
        pytest.fail("cassete do Gemini ausente: grave com `make gravar-cassetes`")
    dados: dict[str, Any] = json.loads(CASSETE.read_text())
    return dados


def test_cassete_foi_gravado_com_o_modelo_em_uso() -> None:
    """Trocar o modelo derruba o contrato até o cassete ser regravado."""
    assert _cassete()["modelo"] == MODELO


def test_cassete_guarda_so_modelo_video_e_texto_sem_cabecalhos() -> None:
    assert set(_cassete()) == {"modelo", "video", "texto"}


def test_resposta_gravada_passa_no_esquema_e_nos_invariantes_de_primeira() -> None:
    """O esquema 1.1 confere início ≤ fim e todo tempo dentro da duração."""
    cassete = _cassete()
    transporte = TransporteFalso(cassete["texto"])

    d = analisar(
        transporte,
        video_uri=VIDEO,
        job_id="contrato",
        video=Video(**cassete["video"]),
    )

    assert d.versao_esquema == "1.1"
    assert d.programa.resumo
    assert len(transporte.chamadas) == 1


def test_grava_so_a_resposta_que_passou_no_esquema(tmp_path: Path) -> None:
    destino = tmp_path / "cassete.json"

    gravar(
        TransporteFalso("lixo", BOA),
        video_uri=VIDEO,
        video=VIDEO_CONFIAVEL,
        destino=destino,
    )

    cassete = json.loads(destino.read_text())
    assert cassete == {
        "modelo": "gemini-3.5-flash-lite",
        "video": {"sha256": "b" * 64, "duracao_ms": VIDEO_CONFIAVEL.duracao_ms},
        "texto": BOA,
    }
