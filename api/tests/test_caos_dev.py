import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from api import caos_dev


class _ApiFalsa:
    def requisitar(self, metodo: str, caminho: str, **_: Any) -> tuple[int, Any]:
        if metodo == "POST":
            return 202, {"id": "job-1", "url_de_upload": "http://upload"}
        raise AssertionError("não deve consultar o Job depois que o envio falhou")


def test_envio_do_arquivo_falho_encerra_sem_esperar_o_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clipe = tmp_path / "clipe.mp4"
    clipe.write_bytes(b"dados")
    monkeypatch.setattr(
        requests,
        "post",
        lambda *a, **k: SimpleNamespace(
            status_code=200, headers={"Location": "http://destino"}
        ),
    )
    monkeypatch.setattr(
        requests, "put", lambda *a, **k: SimpleNamespace(status_code=403)
    )

    def sem_espera(_: float) -> None:
        raise AssertionError("não deve esperar")

    monkeypatch.setattr(time, "sleep", sem_espera)

    relatorio = caos_dev.enviar_clipe(_ApiFalsa(), "A", clipe)  # type: ignore[arg-type]

    nomes = {v.nome: v.ok for v in relatorio.verificacoes}
    assert nomes == {"clipe: envia o arquivo": False}
    assert not relatorio.passou
