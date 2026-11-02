"""A configuração do login no Terraform (#291): o telefone desligado, declarado."""

from pathlib import Path

TF = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()


def test_o_login_por_telefone_fica_declarado_e_desligado() -> None:
    inicio = TF.index('resource "google_identity_platform_config" "mam"')
    config = TF[inicio : TF.index("\n}\n", inicio)]
    sign_in = config[config.index("sign_in {") : config.index("# A chave web")]
    telefone = sign_in[sign_in.index("phone_number {") :]
    assert "enabled = false" in telefone
    assert "test_phone_numbers" not in sign_in
