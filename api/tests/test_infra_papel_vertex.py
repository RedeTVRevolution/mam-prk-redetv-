"""O papel sob medida da Vertex no lugar do roles/aiplatform.user (#302)."""

import re
from pathlib import Path

MODULO = Path(__file__).resolve().parents[2] / "infra" / "modulos" / "mam"
TF = "\n".join(p.read_text() for p in sorted(MODULO.glob("*.tf")))
ADR = Path(__file__).resolve().parents[2] / "docs/adr/0002-terraform-iam-aditivo.md"


def _bloco(cabecalho: str) -> str:
    return TF[TF.index(cabecalho) :].split("\nresource ")[0].split("\nlocals ")[0]


def _permissoes(recurso: str) -> list[str]:
    bloco = _bloco(f'resource "google_project_iam_custom_role" "{recurso}"')
    lista = re.search(r"permissions = \[(.*?)\]", bloco)
    assert lista
    return re.findall(r'"([^"]+)"', lista.group(1))


def test_o_papel_aiplatform_user_nao_esta_mais_no_terraform() -> None:
    codigo = "\n".join(
        linha for linha in TF.splitlines() if not linha.lstrip().startswith("#")
    )
    assert "roles/aiplatform.user" not in codigo


def test_o_papel_de_predicao_so_tem_a_predicao() -> None:
    assert _permissoes("vertex_predicao") == ["aiplatform.endpoints.predict"]


def test_o_papel_da_avaliacao_soma_so_o_evaluate_instances() -> None:
    assert _permissoes("vertex_avaliacao") == [
        "aiplatform.endpoints.predict",
        "aiplatform.locations.evaluateInstances",
    ]


def test_cada_conta_da_vertex_tem_o_papel_certo() -> None:
    projeto = TF[TF.index("papeis_no_projeto = {") : TF.index("papeis_nos_buckets")]
    for conta in (
        "web",
        "analise",
        "indexacao",
        "referencias",
        "identificacao",
        "comparacao",
        "objetos",
    ):
        linha = re.search(rf"^\s+{conta}\s+= \[(.*)\]$", projeto, re.MULTILINE)
        assert linha, conta
        assert "local.papel_vertex_predicao" in linha.group(1), conta
        assert "local.papel_vertex_avaliacao" not in linha.group(1), conta
    avaliacao = re.search(r"^\s+avaliacao\s+= \[(.*)\]$", projeto, re.MULTILINE)
    assert avaliacao
    assert "local.papel_vertex_avaliacao" in avaliacao.group(1)
    assert "local.papel_vertex_predicao" not in avaliacao.group(1)


def test_as_concessoes_esperam_os_papeis_e_as_chaves_sao_conhecidas_no_plan() -> None:
    assert (
        'papel_vertex_predicao  = "projects/${var.projeto}/roles/mamVertexPredicao"'
        in TF
    )
    assert 'role_id     = "mamVertexPredicao"' in TF
    assert 'role_id     = "mamVertexAvaliacao"' in TF
    bloco = _bloco('resource "google_project_iam_member" "mam"')
    assert "google_project_iam_custom_role.vertex_predicao" in bloco
    assert "google_project_iam_custom_role.vertex_avaliacao" in bloco


def test_a_adr_descreve_o_papel_sob_medida() -> None:
    adr = ADR.read_text()
    assert "mamVertexPredicao" in adr and "mamVertexAvaliacao" in adr
    assert "Antes da produção, essas contas passam" not in adr
