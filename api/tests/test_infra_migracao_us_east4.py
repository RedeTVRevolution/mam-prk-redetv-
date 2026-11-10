"""Troca da região para us-east4 (#537): o plan só cria, graças à lista de endereços que o
wizard (#538) tira do estado do Terraform antes do apply."""

import re
from pathlib import Path

RAIZ = Path(__file__).parents[2]
MODULO = RAIZ / "infra" / "modulos" / "mam"
LISTA = RAIZ / "infra" / "migracao-us-east4" / "enderecos-recriados.txt"

# Dependentes que o provedor recria quando o recurso de que dependem é recriado (o atributo
# que muda é ForceNew neles). O que fica de fora atualiza no lugar: a assinatura do webhook
# (push_endpoint), a do BigQuery (bigquery_config.table), o backend service do balanceador.
TIPOS_QUE_RECRIAM = re.compile(
    r"google_(storage_bucket_iam_member|bigquery_dataset_iam_member|bigquery_table|"
    r"bigquery_table_iam_member|artifact_registry_repository_iam_member|"
    r"cloud_run_v2_job_iam_member|cloud_run_v2_service_iam_member|kms_crypto_key|"
    r"kms_crypto_key_iam_member|firestore_index|firestore_field|firestore_backup_schedule)$"
)
# A condição do papel nomeia o banco do Firestore: o atributo é ForceNew e, com
# create_before_destroy, o plan mostraria `delete`. Sem chave de for_each: o `state rm` no
# recurso tira todas as instâncias, e o create do iam_member é idempotente.
MAIS_UM = {"google_project_iam_member.mam"}


def _recursos() -> dict[str, str]:
    achados = {}
    for arquivo in sorted(MODULO.glob("*.tf")):
        for m in re.finditer(
            r'^resource "(\w+)" "(\w+)" \{\n(.*?)^\}\n',
            arquivo.read_text(),
            re.DOTALL | re.MULTILINE,
        ):
            achados[f"{m[1]}.{m[2]}"] = m[3]
    return achados


def _enderecos_da_lista() -> list[str]:
    linhas = [linha.strip() for linha in LISTA.read_text().splitlines()]
    return [linha for linha in linhas if linha and not linha.startswith("#")]


def _esperados() -> set[str]:
    recursos = _recursos()
    # Fora do `regiao_gpu`/`regiao_da_busca`, que já estão em us-east4 e não mudam.
    sementes = {
        k
        for k, corpo in recursos.items()
        if re.search(r"(?:location|region|location_id)\s*=\s*var\.regiao\b(?!_)", corpo)
    }
    # Locals que embrulham um recurso (ex.: origens_da_aplicacao) entram como a dependência.
    por_local: dict[str, set[str]] = {}
    for arquivo in MODULO.glob("*.tf"):
        for m in re.finditer(
            r"^  (\w+)\s*=\s*([^\n]*google_[^\n]*)$", arquivo.read_text(), re.MULTILINE
        ):
            por_local.setdefault(m[1], set()).update(
                re.findall(r"(google_\w+\.\w+)", m[2])
            )
    esperados = set(sementes)
    mudou = True
    while mudou:
        mudou = False
        for k, corpo in recursos.items():
            if k in esperados or not (
                TIPOS_QUE_RECRIAM.match(k.split(".")[0]) or k in MAIS_UM
            ):
                continue
            refs = set(re.findall(r"(google_\w+\.\w+)", corpo))
            for nome in re.findall(r"local\.(\w+)", corpo):
                refs |= por_local.get(nome, set())
            if refs & esperados:
                esperados.add(k)
                mudou = True
    return esperados


def test_a_lista_do_wizard_e_exatamente_o_que_o_plan_recriaria() -> None:
    assert set(_enderecos_da_lista()) == {f"module.mam.{k}" for k in _esperados()}


def test_a_lista_tem_so_enderecos_do_modulo_sem_duplicata_nem_chave() -> None:
    enderecos = _enderecos_da_lista()
    assert enderecos and len(enderecos) == len(set(enderecos))
    for endereco in enderecos:
        assert re.fullmatch(r"module\.mam\.google_\w+\.\w+", endereco), endereco
        assert endereco.removeprefix("module.mam.") in _recursos(), endereco


def test_o_que_ja_esta_em_us_east4_ou_atualiza_no_lugar_fica_fora_da_lista() -> None:
    lista = "\n".join(_enderecos_da_lista())
    assert "_gpu" not in lista  # mam_gpu, sub-rede e Jobs da GPU não mudam de região
    for fica in (
        "google_pubsub_subscription.entrega_do_webhook",
        "google_pubsub_subscription.uso_no_bigquery",
        "google_compute_backend_service.web",
        "time_sleep",
    ):
        assert fica not in lista


def test_uma_so_variavel_de_regiao_para_o_que_nao_e_gpu_nem_busca() -> None:
    texto = "\n".join(f.read_text() for f in MODULO.glob("*.tf"))
    assert not re.search(r'variable "regiao_do_(bigquery|model_armor)"', texto)
    assert not re.search(r"var\.regiao_do_(bigquery|model_armor)", texto)


def test_nenhum_recurso_do_modulo_cai_em_sao_paulo() -> None:
    for arquivo in (
        *MODULO.glob("*.tf"),
        *MODULO.glob("*.yaml"),
        RAIZ / "infra" / "main.tf",
    ):
        assert "southamerica-east1" not in arquivo.read_text(), arquivo.name


def test_os_nomes_novos_derivam_da_regiao_e_so_o_modulo_os_monta() -> None:
    main = (MODULO / "main.tf").read_text()
    seguranca = (MODULO / "banco_de_seguranca.tf").read_text()
    faturamento = (MODULO / "faturamento.tf").read_text()
    assert 'marca_da_regiao = replace(var.regiao, "-", "")' in main
    assert '"${var.projeto}-${local.marca_da_regiao}-${s}"' in main
    assert (
        "${local.marca_da_regiao}" in seguranca
        and "${local.marca_da_regiao}" in faturamento
    )
    assert re.search(
        r'variable "banco_firestore" \{[^}]*default\s+= "mam-principal"', main
    )


def test_os_outputs_que_o_wizard_le() -> None:
    for arquivo in (MODULO / "main.tf", RAIZ / "infra" / "main.tf"):
        texto = arquivo.read_text()
        for saida in (
            "buckets",
            "datasets_bigquery",
            "banco_firestore",
            "banco_de_seguranca",
            "regiao",
        ):
            assert f'output "{saida}"' in texto, (arquivo.name, saida)


def test_os_bancos_novos_mantem_protecao_e_recuperacao() -> None:
    for corpo in (
        _recursos()["google_firestore_database.mam"],
        _recursos()["google_firestore_database.seguranca"],
    ):
        assert (
            "delete_protection_state" in corpo and "DELETE_PROTECTION_ENABLED" in corpo
        )
        assert "POINT_IN_TIME_RECOVERY_ENABLED" in corpo


def test_os_nomes_padrao_dos_bancos_passam_na_regra_do_firestore() -> None:
    # A API recusa o ID com menos de 4 caracteres ("mam" derrubou o apply da troca em 10/11).
    regra = re.compile(r"^[a-z][a-z0-9-]{2,61}[a-z0-9]$")
    for arquivo in (
        RAIZ / "infra" / "main.tf",
        RAIZ / "infra" / "ambientes" / "prod" / "main.tf",
        MODULO / "main.tf",
    ):
        padrao = re.search(
            r'variable "banco_firestore" \{[^}]*default\s+= "([^"]+)"',
            arquivo.read_text(),
        )
        assert padrao and regra.match(padrao.group(1)), arquivo
