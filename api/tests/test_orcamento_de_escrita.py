"""O orçamento de escrita da busca no emulador do Firestore (#460). A conta pura e o
`AgentRetrieval` com o orçamento em memória estão em `test_agent_retrieval.py`."""

import os
import uuid

import pytest
from google.api_core.exceptions import Aborted
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1.transaction import Transaction

from api.orcamento_de_escrita import (
    TETO_DA_ESPERA_SOB_DISPUTA_S,
    OrcamentoFirestore,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="sem emulador do Firestore"
)


@pytest.fixture
def orcamento() -> OrcamentoFirestore:
    cliente = firestore.Client(
        project="teste",
        credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
    )
    return OrcamentoFirestore(cliente, colecao=f"orcamento-{uuid.uuid4().hex}")


def test_reserva_grava_e_o_proximo_processo_le(orcamento: OrcamentoFirestore) -> None:
    assert orcamento.reservar("col", 2000, 2700, 100.0) == 0
    # Outro processo, a mesma coleção da busca: 2.000 + 1.000 não cabem em 2.700.
    assert orcamento.reservar("col", 1000, 2700, 110.0) == pytest.approx(50.0)
    # Outra coleção da busca tem orçamento à parte.
    assert orcamento.reservar("outra", 1000, 2700, 110.0) == 0
    # A primeira reserva saiu da janela.
    assert orcamento.reservar("col", 1000, 2700, 160.5) == 0


def test_disputa_esgotada_vira_espera_curta(
    orcamento: OrcamentoFirestore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def disputado(self: Transaction) -> None:
        raise Aborted("disputa")  # type: ignore[no-untyped-call]

    monkeypatch.setattr(Transaction, "_commit", disputado)
    espera = orcamento.reservar("col", 10, 2700, 0.0)
    assert 0 <= espera <= TETO_DA_ESPERA_SOB_DISPUTA_S
