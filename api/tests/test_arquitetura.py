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
    novas = _violacoes(API, FERRAMENTAS)
    assert not novas, (
        "módulo de produção importando ferramenta (mova o que ele usa para a produção; "
        f"ferramenta nova entra em FERRAMENTAS): {sorted(novas)}"
    )


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


def _fecho(modulo: str) -> set[str]:
    visto: set[str] = set()
    pendentes = [modulo]
    while pendentes:
        atual = pendentes.pop()
        arquivo = API / f"{atual}.py"
        if atual in visto or not arquivo.exists():
            continue
        visto.add(atual)
        pendentes += _importados(arquivo)
    return visto


def test_leitura_do_painel_nao_puxa_os_modulos_de_lote() -> None:
    lote = {"taxa_diaria", "taxa_de_correcao", "revisao_do_painel"}
    for modulo in ("taxa_do_painel", "qualidade_do_painel"):
        assert not _fecho(modulo) & lote, (modulo, _fecho(modulo) & lote)


def _importa(codigo: str, modulo: str) -> bool:
    """Se o código importa `modulo` (`api.jobs`), em qualquer ponto: topo, função ou `TYPE_CHECKING`."""
    pacote, _, nome = modulo.rpartition(".")
    for no in ast.walk(ast.parse(codigo)):
        if isinstance(no, ast.Import) and any(a.name == modulo for a in no.names):
            return True
        if (
            isinstance(no, ast.ImportFrom)
            and no.level == 0
            and (
                no.module == modulo
                or (no.module == pacote and any(a.name == nome for a in no.names))
            )
        ):
            return True
    return False


# Quem importa o módulo à direita volta ao ciclo que o modelo do Job (#661) desfez.
SEM_IMPORTAR = {
    "ciclo_de_vida": "api.jobs",
    "leitura_da_decupagem": "api.jobs",
    "catalogo_dos_jobs": "api.jobs",
    "chaves": "api.jobs",
    "catalogo_de_correcoes": "api.correcoes",
}


def test_modulos_do_modelo_nao_voltam_ao_ciclo_com_as_rotas() -> None:
    for modulo, proibido in SEM_IMPORTAR.items():
        codigo = (API / f"{modulo}.py").read_text()
        assert not _importa(codigo, proibido), f"{modulo} importa {proibido}"


def test_pega_import_de_jobs_no_topo_em_funcao_e_em_type_checking() -> None:
    for codigo in (
        "from api.jobs import Job\n",
        "def f():\n    from api.jobs import Job\n",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from api.jobs import Job\n",
        "from api import jobs\n",
        "import api.jobs\n",
    ):
        assert _importa(codigo, "api.jobs"), codigo
    assert not _importa("from api.modelo_do_job import Job\n", "api.jobs")


# Nomes que deixaram de ser privados (#662): importar o `_` antigo de outro módulo volta ao nome escondido.
# Ficam de fora os de outras áreas (`api.busca._intercalar`, `api.indexacao._registrar`, ...).
NOMES_QUE_DEIXARAM_DE_SER_PRIVADOS = {
    "api.correcoes": {
        "_acha_ocorrencia",
        "_ancora_do_item",
        "_ids_das_pessoas",
        "_intervalo_da_pauta",
        "_intervalo_da_pessoa",
        "_intervalo_do_item",
        "_intervalo_do_objeto",
        "_itens_com_o_id",
        "_objetos",
        "_pautas",
        "_pessoas",
        "_por_inicio",
        "_sobrepoe",
        "_sobrepoe_de_verdade",
        "_sobrepoe_metade",
        "_valor_do_item",
        "_sem_controle",
    },
    "api.regras_das_correcoes": {"_itens"},
    "api.pessoas": {"_em_ordem"},
    "api.decupagem": {"_Intervalo"},
}


def _importes_do_nome_antigo(codigo: str, proibidos: dict[str, set[str]]) -> set[str]:
    return {
        f"{no.module}.{a.name}"
        for no in ast.walk(ast.parse(codigo))
        if isinstance(no, ast.ImportFrom) and no.level == 0 and no.module in proibidos
        for a in no.names
        if a.name in proibidos[no.module]
    }


def test_ninguem_importa_o_nome_com_o_underscore_antigo() -> None:
    achados = {
        (arquivo.relative_to(API).as_posix(), nome)
        for arquivo in API.rglob("*.py")
        for nome in _importes_do_nome_antigo(
            arquivo.read_text(), NOMES_QUE_DEIXARAM_DE_SER_PRIVADOS
        )
    }
    assert not achados, f"importa o nome que deixou de ser privado: {sorted(achados)}"


def test_pega_import_do_nome_antigo() -> None:
    codigo = "def f():\n    from api.correcoes import LIMITE_DO_NOME, _sem_controle\n"
    assert _importes_do_nome_antigo(codigo, NOMES_QUE_DEIXARAM_DE_SER_PRIVADOS) == {
        "api.correcoes._sem_controle"
    }
    assert not _importes_do_nome_antigo(
        "from api.correcoes import sem_controle\nfrom api.busca import _intercalar\n",
        NOMES_QUE_DEIXARAM_DE_SER_PRIVADOS,
    )
