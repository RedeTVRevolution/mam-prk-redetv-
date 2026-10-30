import json
from pathlib import Path

from api.cassete import gravar
from api.tests.test_gemini import BOA, VIDEO, VIDEO_CONFIAVEL, TransporteFalso


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
