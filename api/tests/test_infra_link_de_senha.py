"""O link de senha: o código (`oobCode`) não fica nos logs, e o PATCH recusado da URL de ação sai só do estado."""

from pathlib import Path

LINK = (Path(__file__).parents[2] / "infra/modulos/mam/link_de_senha.tf").read_text()


def test_logs_com_o_codigo_do_link_de_senha_sao_descartados() -> None:
    assert (
        'resource "google_logging_project_exclusion" "codigo_do_link_de_senha"' in LINK
    )
    # O balanceador e o Cloud Run gravam a URL no httpRequest; o uvicorn, no texto do acesso.
    assert 'httpRequest.requestUrl:\\"oobCode=\\"' in LINK
    assert 'textPayload:\\"oobCode=\\"' in LINK
    assert 'httpRequest.referer:\\"oobCode=\\"' in LINK


def test_o_patch_recusado_da_url_de_acao_sai_so_do_estado() -> None:
    # Sem o `removed`, o plano traria um delete e o aplicar-sem-destruir.sh o recusaria.
    assert "from = terraform_data.url_da_acao_de_senha" in LINK
    assert "destroy = false" in LINK
    assert 'resource "terraform_data"' not in LINK
