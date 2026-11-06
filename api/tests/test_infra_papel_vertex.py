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


def test_cada_conta_da_vertex_tem_o_papel_certo() -> None:
    projeto = TF[TF.index("papeis_no_projeto = {") : TF.index("papeis_nos_buckets")]
    for conta in (
        "web",
        "analise",
        "indexacao",
        "identificacao",
        "objetos",
    ):
        linha = re.search(rf"^\s+{conta}\s+= \[(.*)\]$", projeto, re.MULTILINE)
        assert linha, conta
        assert "local.papel_vertex_predicao" in linha.group(1), conta


def test_as_concessoes_esperam_o_papel_e_as_chaves_sao_conhecidas_no_plan() -> None:
    assert re.search(
        r'^\s+id_do_papel_vertex_predicao\s+= "mamVertexPredicao"$', TF, re.MULTILINE
    )
    assert re.search(
        r'^\s+papel_vertex_predicao\s+= "projects/\$\{var\.projeto\}/roles/'
        r'\$\{local\.id_do_papel_vertex_predicao\}"$',
        TF,
        re.MULTILINE,
    )
    recurso = _bloco('resource "google_project_iam_custom_role" "vertex_predicao"')
    assert "role_id     = local.id_do_papel_vertex_predicao\n" in recurso
    bloco = _bloco('resource "google_project_iam_member" "mam"')
    assert "google_project_iam_custom_role.vertex_predicao" in bloco
    assert "vertex_avaliacao" not in TF


def test_a_adr_descreve_o_papel_sob_medida() -> None:
    adr = ADR.read_text()
    assert "mamVertexPredicao" in adr and "mamVertexAvaliacao" not in adr
    assert "Antes da produção, essas contas passam" not in adr
