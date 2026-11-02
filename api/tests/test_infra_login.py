"""A configuração do login no Terraform (#291): o telefone desligado, declarado."""

from pathlib import Path

TF = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()


def _bloco(texto: str, cabecalho: str, fim: str) -> str:
    inicio = texto.index(cabecalho)
    return texto[inicio : texto.index(fim, inicio)]


def test_o_login_por_telefone_fica_declarado_e_desligado() -> None:
    config = _bloco(TF, 'resource "google_identity_platform_config" "mam"', "\n}\n")
    sign_in = _bloco(config, "  sign_in {", "\n  }\n")
    # Corta no primeiro "}": outro bloco depois do telefone não esconde um enabled = true.
    telefone = _bloco(sign_in, "phone_number {", "}")
    assert "enabled = false" in telefone
    assert "test_phone_numbers" not in sign_in
