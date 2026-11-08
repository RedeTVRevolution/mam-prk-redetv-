"""Só os arquivos de entrada do bucket aceitos expiram depois de sete dias."""

import re
from pathlib import Path


def test_so_copia_limpa_e_audio_expiram_no_bucket_aceitos() -> None:
    texto = (
        Path(__file__).resolve().parents[2] / "infra/modulos/mam/main.tf"
    ).read_text()
    bucket = texto.split('resource "google_storage_bucket" "mam" {')[1].split("\n}\n")[
        0
    ]
    regras = bucket.split('dynamic "lifecycle_rule"')[1:]
    regra = next((r for r in regras if 'each.key == "aceitos"' in r), "")

    assert regra
    assert re.search(r'for_each\s*=\s*each.key == "aceitos" \? \[1\] : \[\]', regra)
    assert re.search(r"age\s*=\s*7\b", regra)
    assert re.search(r'matches_suffix\s*=\s*\["copia_limpa.mp4", "audio.wav"\]', regra)
    assert re.search(r'type\s*=\s*"Delete"', regra)
    for preservado in ("proxy.mp4", "transcricao.json", "leitura_da_tela.json"):
        assert preservado not in regra
