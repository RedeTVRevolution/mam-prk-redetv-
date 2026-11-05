"""Exceção de índice de `cortes_ms` (#361): a lista dos cortes não entra no índice do Firestore."""

import re
from pathlib import Path

TF = (
    Path(__file__).parents[2] / "infra" / "modulos" / "mam" / "cortes_sem_indice.tf"
).read_text()
SEM_COMENTARIOS = "\n".join(
    linha for linha in TF.splitlines() if not linha.strip().startswith("#")
)


def test_cortes_ms_fica_fora_do_indice_da_colecao_de_jobs() -> None:
    assert 'resource "google_firestore_field" "jobs_cortes_ms"' in SEM_COMENTARIOS
    assert re.search(r'collection\s*=\s*"jobs"', SEM_COMENTARIOS)
    assert re.search(r'field\s*=\s*"cortes_ms"', SEM_COMENTARIOS)
    # `index_config {}` vazio: nenhum índice, nem de ordem nem de array.
    assert re.search(r"index_config\s*\{\s*\}", SEM_COMENTARIOS)


def test_a_excecao_so_tira_o_indice_e_nao_mexe_em_ttl() -> None:
    assert "ttl_config" not in SEM_COMENTARIOS
