"""O código do link de senha (`oobCode`) vai na URL de `/redefinir-senha`: nenhum log o guarda."""

from pathlib import Path

LINK = (Path(__file__).parents[2] / "infra/modulos/mam/link_de_senha.tf").read_text()


def test_logs_com_o_codigo_do_link_de_senha_sao_descartados() -> None:
    assert (
        'resource "google_logging_project_exclusion" "codigo_do_link_de_senha"' in LINK
    )
    # O balanceador e o Cloud Run gravam a URL no httpRequest; o uvicorn, no texto do acesso.
    assert 'httpRequest.requestUrl:\\"oobCode=\\"' in LINK
    assert 'textPayload:\\"oobCode=\\"' in LINK
