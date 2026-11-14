"""A produção não importa ferramenta (#639): o sentido errado quebraria a API, os Jobs e as imagens com GPU."""

import ast
from pathlib import Path

API = Path(__file__).parents[1]

# Ferramenta é o que está nesta lista fechada (ou em `api/ferramentas/`), não o que o Makefile chama por `-m`.
# Ferramenta nova entra aqui.
FERRAMENTAS = {
    "aceite_dos_esquemas",
    "apagar_referencias_web",
    "atribuir_papeis",
    "caos",
    "caos_dev",
    "carga_dev",
    "carregar_marcas",
    "carregar_programas",
    "cassete",
    "comparador",
    "comparar_detectores",
    "comparar_leituras",
    "comparar_objetos",
    "criar_colecao_da_busca",
    "documentacao_dos_sistemas",
    "emitir_chave",
    "firestore_em_escala",
    "gerir_chaves",
    "gravar_mes_nos_jobs",
    "gravar_versao_nos_jobs",
    "importar_gabarito",
    "limpar_banco_padrao",
    "limpar_residuos_da_purga",
    "medir_agrupamento_de_objetos",
    "medir_busca",
    "medir_florence",
    "medir_juncao",
    "migrar_banco_de_seguranca",
    "pre_voo",
    "preencher_catalogo_dos_jobs",
    "preencher_filtros_da_busca",
    "preencher_planos_recorrentes",
    "registrar_webhook",
    "regressao",
    "regressao_da_versao",
    "reprocessar_versao",
    "sondar_busca",
}

# Violações que sobram (expand-contract): #650 e #651 tiram as suas, #652 as últimas e apaga a lista.
EXCECOES = {
    ("comparar_passadas", "comparador"),
    ("comparar_passadas", "comparar_objetos"),
    ("passadas", "comparar_objetos"),
    ("planos_recorrentes", "medir_agrupamento_de_objetos"),
    ("taxa_diaria", "reprocessar_versao"),
    ("taxa_de_correcao", "reprocessar_versao"),
}


def _importados(arquivo: Path) -> set[str]:
    """Os módulos de `api/` que o arquivo importa, também dentro de funções e sob `TYPE_CHECKING`."""
    achados: set[str] = set()
    for no in ast.walk(ast.parse(arquivo.read_text())):
        if isinstance(no, ast.Import):
            achados |= {
                a.name.split(".")[1] for a in no.names if a.name.startswith("api.")
            }
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            if no.module == "api":
                achados |= {a.name for a in no.names}
            elif no.module.startswith("api."):
                achados.add(no.module.split(".")[1])
        elif isinstance(no, ast.ImportFrom) and no.level == 1:
            achados |= (
                {no.module.split(".")[0]} if no.module else {a.name for a in no.names}
            )
    return achados


def _violacoes(api: Path, ferramentas: set[str]) -> set[tuple[str, str]]:
    """Pares (módulo de produção, ferramenta que ele importa)."""
    ferramentas = ferramentas | {"ferramentas"}  # o pacote `api/ferramentas/` inteiro
    return {
        (arquivo.stem, alvo)
        for arquivo in api.glob("*.py")
        if arquivo.stem not in ferramentas
        for alvo in _importados(arquivo) & ferramentas
    }


def test_producao_nao_importa_ferramenta() -> None:
    novas = _violacoes(API, FERRAMENTAS) - EXCECOES
    assert not novas, (
        "módulo de produção importando ferramenta (mova o que ele usa para a produção; "
        f"ferramenta nova entra em FERRAMENTAS): {sorted(novas)}"
    )


def test_excecao_velha_nao_fica() -> None:
    velhas = EXCECOES - _violacoes(API, FERRAMENTAS)
    assert not velhas, f"exceção que já não é violação, tire da lista: {sorted(velhas)}"


def test_todo_nome_da_lista_existe() -> None:
    faltam = {n for n in FERRAMENTAS if not (API / f"{n}.py").exists()}
    assert not faltam, f"ferramenta da lista sem arquivo: {sorted(faltam)}"


def test_pega_import_novo_de_ferramenta(tmp_path: Path) -> None:
    (tmp_path / "producao.py").write_text(
        "def f():\n    from api.ferramentas.gadget import x\n"
    )
    (tmp_path / "gadget_ligado.py").write_text("from api import medidor\n")
    assert _violacoes(tmp_path, {"medidor"}) == {
        ("producao", "ferramentas"),
        ("gadget_ligado", "medidor"),
    }
