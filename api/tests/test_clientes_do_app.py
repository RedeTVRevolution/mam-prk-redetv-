"""O app do ambiente abre um cliente comum e um de segurança, não um por repositório (#673)."""

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import google.auth
import pytest
from google.cloud import firestore

import api.main

AMBIENTE = {
    "GCP_PROJECT_ID": "proj",
    "FIRESTORE_BANCO_DE_SEGURANCA": "seguranca-teste",
    "BUCKET_QUARENTENA": "q",
    "BUCKET_ACEITOS": "a",
    "BUCKET_DECUPAGENS": "d",
    "BUCKET_REFERENCIAS": "r",
    "WORKFLOW_REGIAO": "r",
    "WORKFLOW_VALIDACAO": "w",
    "INDEXACAO_REGIAO": "r",
    "INDEXACAO_JOB": "j",
    "BIGQUERY_DATASET": "d",
    "BIGQUERY_TABELA": "t",
    "BIGQUERY_REGIAO": "r",
    "BIGQUERY_TABELA_DE_JOBS": "j",
    "BIGQUERY_TABELA_DE_EVENTOS": "e",
    "BIGQUERY_TABELA_DE_REVISAO": "v",
}


def test_o_app_do_ambiente_abre_dois_clientes_do_firestore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for nome, valor in AMBIENTE.items():
        monkeypatch.setenv(nome, valor)
    abertos: list[dict[str, Any]] = []

    def fabrica(**kwargs: Any) -> MagicMock:
        abertos.append(kwargs)
        return MagicMock()

    monkeypatch.setattr(firestore, "Client", fabrica)
    monkeypatch.setattr("google.cloud.storage.Client", lambda **_: MagicMock())
    # Sem credenciais da máquina: o CI não tem ADC.
    monkeypatch.setattr(google.auth, "default", lambda **_: (MagicMock(), "proj"))
    caminho = Path(api.main.__file__)
    # Uma cópia do módulo: o `api.main` do processo não é remontado.
    spec = importlib.util.spec_from_file_location("api._main_do_ambiente", caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "api._main_do_ambiente", modulo)
    spec.loader.exec_module(modulo)

    assert [a["database"] for a in abertos] == ["(default)", "seguranca-teste"]
