"""Índices da lista por mês (#479)."""

import re
from pathlib import Path

MODULO = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
TF = "\n".join(
    (MODULO / nome).read_text() for nome in ("main.tf", "listagem_por_mes.tf")
)
SEM_COMENTARIOS = "\n".join(
    linha for linha in TF.splitlines() if not linha.strip().startswith("#")
)


def test_indices_compostos_levam_o_mes_e_ordenam_por_envio() -> None:
    bloco = SEM_COMENTARIOS.split('resource "google_firestore_index" "acervo_por_mes"')[
        1
    ].split("\nresource ")[0]
    assert re.search(r'collection\s*=\s*"jobs"', bloco)
    assert re.search(
        r'field_path\s*=\s*"mes_exibicao"\s*order\s*=\s*"ASCENDING"\s*\}\s*'
        r'fields \{\s*field_path\s*=\s*"criado_em"\s*order\s*=\s*"DESCENDING"',
        bloco,
    )
