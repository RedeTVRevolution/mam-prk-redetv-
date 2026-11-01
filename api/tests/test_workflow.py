"""Definição do Workflows da validação: o comportamento real é conferido no #14."""

import re
from pathlib import Path

import pytest

from api.rostos_dos_palpites import PREFIXO_DOS_PALPITES

DEFINICAO = Path(__file__).parents[2] / "infra" / "validacao.workflow.yaml"


def _texto() -> str:
    return DEFINICAO.read_text()


def test_roda_o_job_com_override_de_job_id() -> None:
    texto = _texto()

    assert "googleapis.run.v2.projects.locations.jobs.run" in texto
    assert "name: JOB_ID" in texto
    assert "${job_id}" in texto


def test_falha_da_execucao_grava_falhou_com_arquivo_corrompido() -> None:
    texto = _texto()

    assert "try:" in texto and "except:" in texto
    # O `raise` repassa o erro da execução: sem `as: e`, a variável não existe.
    assert "as: e" in texto and "raise: $${e}" in texto
    assert "googleapis.firestore.v1.projects.databases.documents.patch" in texto
    assert "arquivo_corrompido" in texto
    assert "falhou" in texto


def test_roda_o_job_de_analise_so_se_o_job_esta_em_analisando() -> None:
    texto = _texto()

    leitura = texto.index("documents.get")
    condicao = texto.index('estado.stringValue == "analisando"')
    analisa = texto.index("- analisa:")
    assert leitura < condicao < analisa
    passo = texto[analisa:]
    assert "googleapis.run.v2.projects.locations.jobs.run" in passo
    assert "jobs/${job_de_analise}" in passo
    assert "name: JOB_ID" in passo and "value: $${job_id}" in passo
    # A análise não é mais uma chamada HTTP: o teto de 1800 s do Workflows não vale.
    assert "http.post" not in texto and "url_da_analise" not in texto
    # O conector espera mais que o timeout de 21600 s do Job, não o padrão de 1800 s.
    assert "timeout: 21900" in passo
    # Fora de `analisando` o fluxo pula a análise.
    assert "next: fim" in texto


def test_falha_da_analise_grava_analise_falhou() -> None:
    texto = _texto()

    depois = texto[texto.index("- analisa:") :]
    assert "except:" in depois and "as: e" in depois
    assert "stringValue: analise_falhou" in depois
    assert "stringValue: falhou" in depois
    assert "raise: $${e}" in depois


def test_falha_da_chamada_nao_sobrescreve_job_que_ja_saiu_de_analisando() -> None:
    texto = _texto()

    depois_da_chamada = texto[texto.index("- analisa:") :]
    releitura = depois_da_chamada.index("documents.get")
    condicao = depois_da_chamada.index('estado.stringValue != "analisando"')
    patch = depois_da_chamada.index("documents.patch")
    assert releitura < condicao < patch
    # O patch só vale se o documento não mudou desde a releitura.
    assert "updateTime: $${atual.updateTime}" in depois_da_chamada


def test_objeto_sem_job_nao_derruba_a_leitura() -> None:
    texto = _texto()

    leitura = texto[texto.index("le_o_job:") : texto.index("so_se_analisando:")]
    assert "e.code == 404" in leitura and "next: fim" in leitura


def test_falha_da_execucao_nao_sobrescreve_job_cancelado() -> None:
    texto = _texto()

    excecao = texto[texto.index("le_antes_de_marcar:") : texto.index("le_o_job:")]
    releitura = excecao.index("documents.get")
    condicao = excecao.index('estado.stringValue == "cancelado"')
    patch = excecao.index("documents.patch")
    assert releitura < condicao < patch
    # O patch só vale se o documento não mudou desde a releitura.
    assert "updateTime: $${antes.updateTime}" in excecao
    # Um objeto sem Job correspondente não cria documento: a releitura dá 404.
    assert "erro_da_leitura.code == 404" in excecao


def test_ordem_e_validacao_transcricao_analise() -> None:
    texto = _texto()

    valida = texto.index("- valida:")
    transcreve = texto.index("- transcreve:")
    analisa = texto.index("- analisa:")
    assert valida < transcreve < analisa
    assert "jobs/${job_de_validacao}" in texto
    assert "jobs/${job_de_transcricao}" in texto
    # A transcrição só roda com o Job em `analisando`.
    assert texto.index('estado.stringValue == "analisando"') < transcreve


def test_transcricao_roda_o_job_com_override_de_job_id() -> None:
    texto = _texto()

    passo = texto[texto.index("- transcreve:") : texto.index("- analisa:")]
    assert "googleapis.run.v2.projects.locations.jobs.run" in passo
    assert "jobs/${job_de_transcricao}" in passo
    assert "name: JOB_ID" in passo and "value: $${job_id}" in passo
    # O conector espera mais que o timeout de 21600 s do Job, não o padrão de 1800 s.
    assert "timeout: 21900" in passo


def test_falha_da_transcricao_grava_transcricao_falhou_sem_sobrescrever_outro_estado() -> (
    None
):
    texto = _texto()

    passo = texto[texto.index("- transcreve:") : texto.index("- analisa:")]
    releitura = passo.index("documents.get")
    condicao = passo.index('estado.stringValue != "analisando"')
    patch = passo.index("documents.patch")
    assert releitura < condicao < patch
    assert "updateTime: $${durante.updateTime}" in passo
    assert "stringValue: transcricao_falhou" in passo
    assert "raise: $${e}" in passo


def test_ocr_da_tela_roda_depois_da_transcricao_e_antes_da_analise() -> None:
    texto = _texto()

    transcreve = texto.index("- transcreve:")
    le_a_tela = texto.index("- le_a_tela:")
    analisa = texto.index("- analisa:")
    assert transcreve < le_a_tela < analisa
    passo = texto[le_a_tela:analisa]
    assert "googleapis.run.v2.projects.locations.jobs.run" in passo
    assert "jobs/${job_de_ocr}" in passo
    assert "name: JOB_ID" in passo and "value: $${job_id}" in passo
    assert "timeout: 29100" in passo


def test_falha_do_ocr_grava_ocr_falhou_sem_sobrescrever_outro_estado() -> None:
    texto = _texto()

    passo = texto[texto.index("- le_a_tela:") : texto.index("- analisa:")]
    releitura = passo.index("documents.get")
    condicao = passo.index('estado.stringValue != "analisando"')
    patch = passo.index("documents.patch")
    assert releitura < condicao < patch
    assert "updateTime: $${durante_o_ocr.updateTime}" in passo
    assert "stringValue: ocr_falhou" in passo
    assert "raise: $${e}" in passo


def test_job_de_ocr_no_main_tf_sem_internet_e_na_rede_da_validacao() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()

    job = main[main.index('resource "google_cloud_run_v2_job" "ocr"') :].split(
        "\nresource "
    )[0]
    assert "google_compute_network.validacao.id" in job
    assert "google_compute_subnetwork.validacao.id" in job
    assert "var.imagem_ocr" in job
    assert "max_retries     = 0" in job
    assert "external_ip" not in main and "google_compute_router_nat" not in main
    assert re.search(r"job_de_ocr\s+= google_cloud_run_v2_job\.ocr\.name", main)


def test_job_de_analise_no_main_tf_e_o_que_o_workflow_roda() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()

    job = main[main.index('resource "google_cloud_run_v2_job" "analise"') :].split(
        "\nresource "
    )[0]
    assert 'args    = ["-m", "api.analise"]' in job
    assert "max_retries     = 0" in job
    assert "JANELAS_EM_PARALELO" in job and "var.janelas_em_paralelo" in job
    assert re.search(r"job_de_analise\s+= google_cloud_run_v2_job\.analise\.name", main)
    assert "google_cloud_run_v2_service.analise" not in main
    # O Job de análise dura mais que o teto de 1800 s da chamada HTTP do Workflows.
    assert 'timeout = "21600s"' in job


def test_quadros_chave_rodam_depois_da_analise_e_a_falha_deles_nao_derruba_o_job() -> (
    None
):
    texto = _texto()

    analisa = texto.index("- analisa:")
    quadros = texto.index("- tira_os_quadros:")
    fim = texto.index("- fim:")
    assert analisa < quadros < fim
    passo = texto[quadros:fim]
    assert "googleapis.run.v2.projects.locations.jobs.run" in passo
    assert "jobs/${job_de_quadros}" in passo
    assert "name: JOB_ID" in passo and "value: $${job_id}" in passo
    # O Job já está concluído: sem os JPEGs a Decupagem segue valendo.
    assert "except:" in passo and "sys.log" in passo and "raise" not in passo


def test_job_de_quadros_no_main_tf_sem_internet_com_a_imagem_da_validacao() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()

    job = main[main.index('resource "google_cloud_run_v2_job" "quadros"') :].split(
        "\nresource "
    )[0]
    assert "google_compute_network.validacao.id" in job
    assert "var.imagem_validacao" in job
    assert 'args    = ["-m", "api.quadros_chave"]' in job
    assert "max_retries     = 0" in job
    assert 'local.buckets["aceitos"]' in job and 'local.buckets["decupagens"]' in job
    assert re.search(r"job_de_quadros\s+= google_cloud_run_v2_job\.quadros\.name", main)
    # Lê a cópia limpa e grava os JPEGs e a Decupagem; não escreve em aceitos.
    assert 'quadros = { aceitos = "roles/storage.objectViewer"' in main
    assert 'decupagens = "roles/storage.objectUser"' in main


def test_indexacao_roda_depois_dos_quadros_e_a_falha_dela_nao_derruba_o_job() -> None:
    texto = _texto()

    quadros = texto.index("- tira_os_quadros:")
    indexa = texto.index("- indexa:")
    fim = texto.index("- fim:")
    assert quadros < indexa < fim
    passo = texto[indexa:fim]
    assert "jobs/${job_de_indexacao}" in passo
    assert "name: JOB_ID" in passo and "value: $${job_id}" in passo
    assert "except:" in passo and "sys.log" in passo and "raise" not in passo


def test_job_de_indexacao_no_main_tf_com_internet_e_so_a_decupagem() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()

    job = main[main.index('resource "google_cloud_run_v2_job" "indexacao"') :].split(
        "\nresource "
    )[0]
    assert "vpc_access" not in job
    assert 'args    = ["-m", "api.indexacao"]' in job
    assert "max_retries     = 0" in job
    assert "BUSCA_COLECAO" in job and "BUSCA_INDICE_QUADRO" in job
    assert re.search(
        r"job_de_indexacao\s+= google_cloud_run_v2_job\.indexacao\.name", main
    )
    # Só lê a Decupagem; não escreve em bucket nenhum.
    assert 'indexacao = { decupagens = "roles/storage.objectViewer" }' in main


def _segundos(texto: str) -> int:
    return int(texto.strip().removesuffix("s"))


def test_conector_de_cada_passo_espera_mais_que_o_timeout_do_job() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()
    texto = _texto()
    passos = {
        "valida": ("validacao", "- valida:", "- le_o_job:"),
        "transcreve": ("transcricao", "- transcreve:", "- le_a_tela:"),
        "le_a_tela": ("ocr", "- le_a_tela:", "- analisa:"),
        "analisa": ("analise", "- analisa:", "- inicia_identificacao:"),
        "identifica": ("identificacao", "- identifica:", "- inicia_referencias:"),
        "busca_as_referencias": (
            "referencias",
            "- busca_as_referencias:",
            "- inicia_comparacao:",
        ),
        "compara": ("comparacao", "- compara:", "- inicia_quadros_chave:"),
        "tira_os_quadros": ("quadros", "- tira_os_quadros:", "- indexa:"),
        "indexa": ("indexacao", "- indexa:", "- fim:"),
    }
    for nome, (job, de, ate) in passos.items():
        recurso = main[main.index(f'resource "google_cloud_run_v2_job" "{job}"') :]
        recurso = recurso[: recurso.index("\n}\n")]
        job_s = _segundos(re.search(r'timeout\s*=\s*"(\d+s)"', recurso).group(1))  # type: ignore[union-attr]
        passo = texto[texto.index(de) : texto.index(ate)]
        conector = re.search(r"connector_params:\s+timeout: (\d+)", passo)
        assert conector is not None, nome
        assert int(conector.group(1)) > job_s, nome


def test_nenhum_comentario_da_infra_fala_em_ate_10_min() -> None:
    infra = Path(__file__).parents[2] / "infra"
    for arquivo in (infra / "main.tf", DEFINICAO):
        assert "até 10 min" not in arquivo.read_text()


def test_job_de_referencias_no_main_tf_tem_internet_e_o_segredo_e_so_dele() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()

    job = main[main.index('resource "google_cloud_run_v2_job" "referencias"') :].split(
        "\nresource "
    )[0]
    assert "vpc_access" not in job
    assert "max_retries     = 0" in job
    assert 'local.buckets["referencias"]' in job
    assert "google_secret_manager_secret.serpapi.id" in job
    assert 'google_service_account.mam["referencias"]' in job
    assert "google_secret_manager_secret_version" not in main
    acesso = main[
        main.index('resource "google_secret_manager_secret_iam_member"') :
    ].split("\nresource ")[0]
    assert 'google_service_account.mam["referencias"].member' in acesso
    assert main.count("secretAccessor") == 1


ETAPAS = [
    ("valida", "validacao"),
    ("transcreve", "transcricao"),
    ("le_a_tela", "leitura_da_tela"),
    ("analisa", "analise"),
    ("busca_as_referencias", "referencias"),
    ("tira_os_quadros", "quadros_chave"),
    ("indexa", "indexacao"),
]


def test_cada_etapa_grava_o_inicio_antes_e_o_fim_depois_de_rodar() -> None:
    texto = _texto()

    for passo, etapa in ETAPAS:
        inicio = texto.index(
            f"call: marca_inicio\n        args:\n          job_id: $${{job_id}}\n          etapa: {etapa}\n"
        )
        roda = texto.index(f"    - {passo}:\n")
        fim = texto.index(
            f"call: marca_fim\n        args:\n          job_id: $${{job_id}}\n          etapa: {etapa}\n          falhou_na_execucao: false"
        )
        assert inicio < roda < fim


def test_falha_da_execucao_de_cada_etapa_grava_o_fim_como_falhou() -> None:
    texto = _texto()

    for passo, etapa in ETAPAS:
        inicio = texto.index(f"\n    - {passo}:\n")
        corpo = texto[inicio + 1 :]
        corpo = corpo[: re.search(r"\n    - ", corpo[5:]).end() + 5]  # type: ignore[union-attr]
        assert f"etapa: {etapa}\n" in corpo, passo
        assert "falhou_na_execucao: true" in corpo, passo


def test_subworkflow_grava_so_os_campos_da_etapa_sem_mexer_no_estado() -> None:
    texto = _texto()

    marcas = texto[texto.index("\nmarca_inicio:") :]
    assert '"etapas." + etapa' in marcas
    assert 'etapas." + etapa + ".fim"' in marcas
    assert "resultado" in marcas
    assert '"estado"' not in marcas and "estado]" not in marcas
    # Um objeto sem Job não cria documento, e a medição nunca derruba o processamento.
    assert marcas.count("exists: true") == 2
    assert "sys.log" in marcas


def test_quadros_e_indexacao_so_comecam_com_o_job_concluido() -> None:
    texto = _texto()

    guarda = texto.index("so_se_concluido:")
    assert texto.index("- analisa:") < guarda < texto.index("- tira_os_quadros:")
    assert 'estado.stringValue == "concluido"' in texto
    assert "next: inicia_identificacao" in texto[guarda:]


def test_falha_de_cada_etapa_nao_cai_no_encerra_que_a_gravaria_como_concluida() -> None:
    texto = _texto()

    for passo, etapa in ETAPAS:
        excecao = texto[
            texto.index(
                "        except:\n", texto.index(f"\n    - {passo}:\n")
            ) : texto.index(f"\n    - encerra_{etapa}:\n")
        ]
        ultimo_passo = excecao.rstrip().rsplit("\n            - ", 1)[1]
        assert "raise:" in ultimo_passo or "next:" in ultimo_passo, passo


def test_fim_de_etapa_sem_inicio_nao_e_gravado() -> None:
    texto = _texto()

    marca_fim = texto[texto.index("\nmarca_fim:") :]
    guarda = marca_fim.index('["etapas", "mapValue", "fields", etapa]) == null')
    assert guarda < marca_fim.index("grava_o_fim:")


def test_ordem_nova_identificacao_referencias_comparacao_quadros_indexacao() -> None:
    texto = _texto()

    ordem = [
        "- analisa:",
        "- identifica:",
        "- busca_as_referencias:",
        "- compara:",
        "- tira_os_quadros:",
        "- indexa:",
        "- fim:",
    ]
    posicoes = [texto.index(passo) for passo in ordem]
    assert posicoes == sorted(posicoes)
    for job in ("identificacao", "referencias", "comparacao"):
        passo = texto[
            texto.index(
                f"call: marca_inicio\n        args:\n          job_id: $${{job_id}}\n          etapa: {job}"
            ) :
        ]
        assert f"jobs/${{job_de_{job}}}" in passo.split("- tira_os_quadros:")[0]
    # Sem internet: a identificação e a comparação; com internet: só as referências.
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()
    for job in ("identificacao", "referencias", "comparacao"):
        assert f"job_de_{job}" in main


@pytest.mark.parametrize(
    ("passo", "etapa", "seguinte"),
    [
        ("identifica", "identificacao", "inicia_referencias"),
        ("busca_as_referencias", "referencias", "inicia_comparacao"),
        ("compara", "comparacao", "inicia_quadros_chave"),
    ],
)
def test_falha_dos_passos_novos_vai_ao_log_e_a_etapa_e_os_seguintes_rodam(
    passo: str, etapa: str, seguinte: str
) -> None:
    texto = _texto()

    corpo = texto[texto.index(f"\n    - {passo}:\n") + 1 :]
    corpo = corpo[: re.search(r"\n    - ", corpo[5:]).end() + 5]  # type: ignore[union-attr]
    excecao = corpo[corpo.index("except:") :]
    assert "falhou_na_execucao: true" in excecao
    assert "sys.log" in excecao and "raise" not in excecao
    assert f"next: {seguinte}" in excecao
    # Nunca mexem no `estado` do Job: o Job continua `concluido`.
    assert "documents.patch" not in excecao


def test_etapas_dos_jobs_que_gravam_o_proprio_resultado_nao_sao_regravadas_como_concluida() -> (
    None
):
    texto = _texto()

    assert "etapa: identificacao\n          falhou_na_execucao: false" not in texto
    assert "etapa: comparacao\n          falhou_na_execucao: false" not in texto


def _depois_de(texto: str, passo: str) -> str:
    return texto[texto.index(f"- {passo}:") :]


def test_reprocessamento_entra_pelo_job_e_pela_etapa_inicial_do_argumento() -> None:
    texto = _texto()

    escolha = _depois_de(texto, "escolhe_a_entrada")
    assert 'map.get(evento, "etapa_inicial") != null' in escolha
    assert "job_id: $${evento.job_id}" in texto
    assert "etapa_inicial: $${evento.etapa_inicial}" in texto
    # O evento do Eventarc segue rodando tudo, a começar pela validação.
    assert "job_id: $${evento.data.name}" in texto
    assert "etapa_inicial: validacao" in texto


def _destino(texto: str, etapa: str) -> str:
    roteia = _depois_de(texto, "parte_da_etapa")
    achado = re.search(
        rf'etapa_inicial == "{etapa}"\}}\n\s+next: (\w+)',
        roteia.split("- inicia_validacao:")[0],
    )
    assert achado, etapa
    return achado.group(1)


def test_partindo_da_analise_nem_a_transcricao_nem_a_leitura_da_tela_rodam() -> None:
    texto = _texto()

    destino = _destino(texto, "analise")

    assert destino == "inicia_analise"
    # Do destino em diante estão a análise e as etapas depois dela.
    daqui = _depois_de(texto, destino).split("# Tempo de cada etapa")[0]
    assert "jobs/${job_de_analise}" in daqui
    for antes in (
        "job_de_validacao",
        "job_de_transcricao",
        "job_de_ocr",
    ):
        assert antes not in daqui
    for depois in (
        "job_de_identificacao",
        "job_de_referencias",
        "job_de_comparacao",
        "job_de_quadros",
        "job_de_indexacao",
    ):
        assert depois in daqui


def test_partindo_da_indexacao_nada_antes_dela_roda() -> None:
    texto = _texto()

    destino = _destino(texto, "indexacao")

    assert destino == "inicia_indexacao"
    daqui = _depois_de(texto, destino).split("# Tempo de cada etapa")[0]
    assert "jobs/${job_de_indexacao}" in daqui
    for antes in (
        "job_de_validacao",
        "job_de_transcricao",
        "job_de_ocr",
        "job_de_analise",
        "job_de_identificacao",
        "job_de_referencias",
        "job_de_comparacao",
        "job_de_quadros",
    ):
        assert antes not in daqui


def test_partindo_da_comparacao_nem_a_identificacao_nem_as_referencias_rodam() -> None:
    texto = _texto()

    destino = _destino(texto, "comparacao")

    assert destino == "inicia_comparacao"
    daqui = _depois_de(texto, destino).split("# Tempo de cada etapa")[0]
    assert "jobs/${job_de_comparacao}" in daqui
    for antes in (
        "job_de_validacao",
        "job_de_transcricao",
        "job_de_ocr",
        "job_de_analise",
        "job_de_identificacao",
        "job_de_referencias",
    ):
        assert antes not in daqui
    for depois in ("job_de_quadros", "job_de_indexacao"):
        assert depois in daqui


def test_partindo_das_referencias_a_identificacao_nao_roda() -> None:
    texto = _texto()

    destino = _destino(texto, "referencias")

    assert destino == "inicia_referencias"
    daqui = _depois_de(texto, destino).split("# Tempo de cada etapa")[0]
    assert "job_de_identificacao" not in daqui and "job_de_comparacao" in daqui


def test_cada_etapa_de_partida_cai_no_inicio_da_propria_etapa() -> None:
    texto = _texto()

    assert _destino(texto, "transcricao") == "inicia_transcricao"
    assert _destino(texto, "leitura_da_tela") == "inicia_leitura_da_tela"
    assert _destino(texto, "quadros_chave") == "inicia_quadros_chave"
    assert _destino(texto, "identificacao") == "inicia_identificacao"


def test_a_api_so_inicia_execucoes_do_workflow_e_sabe_qual_e() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()

    web = main[main.index("papeis_no_projeto = {") :].split("validacao ")[0]
    assert '"roles/workflows.invoker"' in web
    assert "workflows.admin" not in main and "workflows.editor" not in main
    # O mesmo nome no workflow e na web, pelo local (a referência ao recurso fecha um ciclo).
    assert "name            = local.workflow_validacao" in main
    assert "value = local.workflow_validacao" in main
    assert 'name  = "WORKFLOW_VALIDACAO"' in main
    assert 'name  = "WORKFLOW_REGIAO"' in main


def _job_do_main_tf(nome: str) -> str:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()
    return main[main.index(f'resource "google_cloud_run_v2_job" "{nome}"') :].split(
        "\nresource "
    )[0]


@pytest.mark.parametrize(
    ("nome", "modulo"),
    [("identificacao", "identificacao_job"), ("comparacao", "comparacao_job")],
)
def test_jobs_de_identificacao_e_comparacao_sem_internet_com_a_imagem_do_ffmpeg(
    nome: str, modulo: str
) -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()
    job = _job_do_main_tf(nome)

    assert "google_compute_network.validacao.id" in job
    assert "google_compute_subnetwork.validacao.id" in job
    assert "var.imagem_validacao" in job
    assert f'args    = ["-m", "api.{modulo}"]' in job
    assert "max_retries     = 0" in job
    assert f'google_service_account.mam["{nome}"]' in job
    assert "external_ip" not in main and "google_compute_router_nat" not in main
    assert 'local.buckets["aceitos"]' in job and 'local.buckets["decupagens"]' in job


def test_variaveis_dos_jobs_novos_vem_do_main_tf() -> None:
    ident = _job_do_main_tf("identificacao")
    comp = _job_do_main_tf("comparacao")

    assert "var.limite_de_pessoas_do_modelo_forte" in ident
    assert 'name  = "LIMITE_DE_PESSOAS_DO_MODELO_FORTE"' in ident
    for env, valor in [
        ("LIMIAR_DA_COMPARACAO", "var.limiar_da_comparacao"),
        ("LIMITE_DE_COMPARACOES", "var.limite_de_comparacoes"),
        ("VALIDADE_DAS_REFERENCIAS_DIAS", "var.validade_das_referencias_dias"),
        ("REFERENCIAS_DO_ACERVO", "var.referencias_do_acervo"),
    ]:
        assert f'name  = "{env}"' in comp
        assert valor in comp
    assert 'local.buckets["referencias"]' in comp
    assert 'local.buckets["referencias"]' not in ident


def test_contas_e_papeis_dos_jobs_novos_sao_so_os_combinados() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()

    contas = main.split("for_each     = toset([")[1].split("])")[0]
    for nome in ("identificacao", "comparacao"):
        assert f'"{nome}"' in contas
        assert re.search(
            rf'\n\s+{nome}\s+= \["roles/datastore.user", "roles/aiplatform.user"\]',
            main,
        )
    assert re.search(
        r'identificacao = \{ aceitos = "roles/storage.objectViewer", '
        r'decupagens = "roles/storage.objectUser" \}',
        main,
    )
    assert re.search(
        r'comparacao = \{ aceitos = "roles/storage.objectViewer", '
        r'decupagens = "roles/storage.objectUser", '
        r'referencias = "roles/storage.objectUser" \}',
        main,
    )


def test_so_o_prefixo_dos_palpites_expira_e_o_prazo_vem_da_variavel() -> None:
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()
    bucket = main[main.index('resource "google_storage_bucket" "mam"') :].split(
        "\nresource "
    )[0]
    regra = bucket.split('dynamic "lifecycle_rule"')[1].split('dynamic "cors"')[0]
    variavel = main.split('variable "prazo_dos_palpites_dias"')[1].split("\n}")[0]

    assert 'each.key == "referencias"' in regra
    assert "age            = var.prazo_dos_palpites_dias" in regra
    assert f'matches_prefix = ["{PREFIXO_DOS_PALPITES}"]' in regra
    assert 'type = "Delete"' in regra
    assert regra.count("condition") == 1 and "created_before" not in regra
    assert "default     = 30" in variavel
    assert bucket.count("lifecycle_rule") == 1


def test_limite_de_buscas_e_a_lista_de_nomes_do_job_de_referencias_vem_do_main_tf() -> (
    None
):
    job = _job_do_main_tf("referencias")

    assert 'name  = "LIMITE_DE_BUSCAS_POR_VIDEO"' in job
    assert "var.limite_de_buscas_por_video" in job
    assert 'name  = "BUCKET_DECUPAGENS"' in job and 'local.buckets["decupagens"]' in job
    main = (Path(__file__).parents[2] / "infra" / "main.tf").read_text()
    assert re.search(
        r'referencias = \{ referencias = "roles/storage.objectUser", '
        r'decupagens = "roles/storage.objectViewer" \}',
        main,
    )
