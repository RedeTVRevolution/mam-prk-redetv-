"""Banco do Firestore só de segurança e `datastore.user` com condição por banco (#464)."""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MODULO = RAIZ / "infra" / "modulos" / "mam"
TF = "\n".join(p.read_text() for p in sorted(MODULO.glob("*.tf")))
VARIAVEL = "FIRESTORE_BANCO_DE_SEGURANCA"
CONTAS_DO_PROCESSAMENTO = ("validacao", "transcricao", "ocr", "analise", "quadros")


def _bloco(cabecalho: str) -> str:
    inicio = re.search(rf"^{re.escape(cabecalho)}", TF, re.MULTILINE)
    assert inicio
    return TF[inicio.start() : TF.index("\n}\n", inicio.start())]


def _recursos_com_a_variavel() -> set[str]:
    achados = set()
    for arquivo in sorted(MODULO.glob("*.tf")):
        texto = arquivo.read_text()
        for recurso in re.finditer(
            r'^resource "(google_cloud_run_v2_\w+)" "(\w+)"', texto, re.MULTILINE
        ):
            fim = texto.find("\nresource ", recurso.end())
            corpo = texto[recurso.start() : fim if fim != -1 else len(texto)]
            if f'name  = "{VARIAVEL}"' in corpo:
                achados.add(recurso.group(2))
    return achados


def test_o_banco_de_seguranca_tem_pitr_e_protecao_contra_apagar() -> None:
    banco = _bloco('resource "google_firestore_database" "seguranca"')

    assert "name                              = local.banco_de_seguranca" in banco
    assert 'type                              = "FIRESTORE_NATIVE"' in banco
    assert (
        'point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"' in banco
    )
    assert 'delete_protection_state           = "DELETE_PROTECTION_ENABLED"' in banco


def test_o_nome_do_banco_so_e_montado_no_modulo_e_vai_por_output() -> None:
    assert len(re.findall(r'banco_de_seguranca\s*=\s*"', TF)) == 1
    assert 'output "banco_de_seguranca"' in TF
    for arquivo in ("infra/main.tf", "infra/ambientes/prod/main.tf"):
        assert "module.mam.banco_de_seguranca" in (RAIZ / arquivo).read_text()


def test_a_variavel_chega_so_a_web_e_a_purga() -> None:
    assert _recursos_com_a_variavel() == {"web", "purga"}


def test_os_comandos_do_makefile_recebem_o_banco_de_seguranca() -> None:
    makefile = (RAIZ / "Makefile").read_text()
    for modulo in (
        "api.emitir_chave",
        "api.gerir_chaves listar",
        "api.gerir_chaves revogar",
        "api.atribuir_papeis",
        "api.correcao_de_estado",
        "api.reprocessar_versao",
    ):
        antes = makefile[: makefile.index(f"python -m {modulo}")]
        ultimo_alvo = antes[antes.rindex("\n\n") :]
        assert f"{VARIAVEL}=" in ultimo_alvo, modulo
        assert "output -raw banco_de_seguranca" in ultimo_alvo, modulo


def test_so_a_web_e_a_purga_tem_datastore_user_sem_condicao() -> None:
    iam = _bloco('resource "google_project_iam_member" "mam"')

    assert 'contas_no_banco_de_seguranca = ["web", "purga"]' in TF
    assert 'each.value.papel == "roles/datastore.user"' in iam
    assert "!contains(local.contas_no_banco_de_seguranca, each.value.sa)" in iam
    # A condição limita ao banco `(default)` e não cita o banco de segurança.
    assert (
        'resource.name == \\"projects/${var.projeto}/databases/'
        "${google_firestore_database.mam.name}"
    ) in iam
    expressao = iam.split("expression")[1].split("\n")[0]
    assert "seguranca" not in expressao
    assert "create_before_destroy = true" in iam


def test_os_jobs_do_processamento_tem_datastore_user_e_ficam_com_a_condicao() -> None:
    papeis = _bloco("  papeis_no_projeto = {")
    for conta in CONTAS_DO_PROCESSAMENTO:
        assert re.search(rf'\n\s+{conta}\s+= \["roles/datastore.user"', papeis), conta
    # Nenhuma delas está na lista das contas que entram no banco de segurança.
    lista = re.search(r"contas_no_banco_de_seguranca = \[(.*?)\]", TF)
    assert lista
    for conta in CONTAS_DO_PROCESSAMENTO:
        assert f'"{conta}"' not in lista.group(1)
    assert not (set(CONTAS_DO_PROCESSAMENTO) & _recursos_com_a_variavel())


def test_o_indice_da_auditoria_nasce_no_banco_novo_e_o_antigo_fica() -> None:
    novo = _bloco('resource "google_firestore_index" "auditoria_na_seguranca"')
    antigo = _bloco('resource "google_firestore_index" "auditoria"')

    assert "database   = google_firestore_database.seguranca.name" in novo
    assert "database   = google_firestore_database.mam.name" in antigo


def test_o_banco_de_seguranca_tem_as_mesmas_agendas_de_backup() -> None:
    for nome in ("diaria_na_seguranca", "semanal_na_seguranca"):
        agenda = _bloco(f'resource "google_firestore_backup_schedule" "{nome}"')
        assert "database  = google_firestore_database.seguranca.name" in agenda
    diaria = _bloco('resource "google_firestore_backup_schedule" "diaria_na_seguranca"')
    semanal = _bloco(
        'resource "google_firestore_backup_schedule" "semanal_na_seguranca"'
    )
    assert "daily_recurrence" in diaria and '"604800s"' in diaria
    assert "weekly_recurrence" in semanal and '"8467200s"' in semanal


def test_o_banco_principal_vem_da_variavel_e_chega_a_todo_servico_e_job() -> None:
    assert re.search(r'variable "banco_firestore" \{[^}]*default\s+= "mam"', TF)
    assert "name                    = var.banco_firestore" in _bloco(
        'resource "google_firestore_database" "mam"'
    )
    todos = set()
    for arquivo in sorted(MODULO.glob("*.tf")):
        texto = arquivo.read_text()
        for recurso in re.finditer(
            r'^resource "google_cloud_run_v2_(?:job|service)" "(\w+)"',
            texto,
            re.MULTILINE,
        ):
            fim = texto.find("\nresource ", recurso.end())
            corpo = texto[recurso.start() : fim if fim != -1 else len(texto)]
            assert 'name  = "FIRESTORE_BANCO"' in corpo, recurso.group(1)
            todos.add(recurso.group(1))
    assert {"web", "purga", "validacao", "identificacao", "fim"} <= todos
    for nome in ("main.tf", "ambientes/prod/main.tf"):
        assert "banco_firestore" in (RAIZ / "infra" / nome).read_text(), nome
