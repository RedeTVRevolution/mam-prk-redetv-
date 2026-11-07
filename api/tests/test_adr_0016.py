"""A ADR 0016 (sem organização, dev vira produção) e o Plano que aponta para ela (#373)."""

import re
from pathlib import Path

RAIZ = Path(__file__).parents[2]
ADR = RAIZ / "docs" / "adr" / "0016-sem-organizacao-dev-vira-producao.md"
PLANO = RAIZ / "docs" / "Plano_MAM.md"
MITIGACOES = ["#372", "#369", "#371", "#368", "#366"]


def test_a_adr_cita_os_riscos_aceitos_e_as_mitigacoes_pelos_tickets() -> None:
    texto = ADR.read_text()

    for ticket in [*MITIGACOES, "#370"]:
        assert ticket in texto
    assert "VPC-SC" in texto and "Cloud Armor" in texto and "Data Access" in texto


def test_o_plano_nao_fala_em_staging_nem_vpc_sc_e_aponta_para_a_adr() -> None:
    texto = PLANO.read_text()

    assert "adr/0016-sem-organizacao-dev-vira-producao.md" in texto
    # As menções que sobram só existem para dizer que a decisão tirou o item.
    for linha in texto.splitlines():
        if re.search(r"staging|VPC Service Controls|VPC-SC", linha, re.IGNORECASE):
            assert "ADR 0016" in linha, linha
