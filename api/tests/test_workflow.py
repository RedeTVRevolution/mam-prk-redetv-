"""Definição do Workflows da validação: o comportamento real é conferido no #14."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

MODULO = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
MAIN = MODULO / "main.tf"
DEFINICAO = MODULO / "validacao.workflow.yaml"


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
    condicao = excecao.index('estado.stringValue in ["cancelado", "falhou"]')
    patch = excecao.index("documents.patch")
    assert releitura < condicao < patch
    # O patch só vale se o documento não mudou desde a releitura.
    assert "updateTime: $${antes.updateTime}" in excecao
    # Um objeto sem Job correspondente não cria documento: a releitura dá 404.
    assert "erro_da_leitura.code == 404" in excecao


def _subworkflow(texto: str, nome: str) -> str:
    """O texto de um subworkflow (do nome, no início da linha, ao próximo)."""
    inicio = texto.index(f"\n{nome}:\n")
    resto = texto[inicio + 1 :]
    proximo = re.search(r"\n[a-z_]+:\n", resto)
    return resto[: proximo.start()] if proximo else resto


def _paralelo(texto: str) -> str:
    return texto[texto.index("- roda_em_paralelo:") : texto.index("- inicia_analise:")]


def _ramo(texto: str, nome: str) -> str:
    paralelo = _paralelo(texto)
    ramos = re.split(r"\n\s+- (?=ramo_da_\w+:)", paralelo)
    achado = [r for r in ramos if r.startswith(nome + ":")]
    assert achado, nome
    return achado[0]


def test_ordem_e_validacao_transcricao_analise() -> None:
    texto = _texto()

    valida = texto.index("- valida:")
    paralelo = texto.index("- roda_em_paralelo:")
    analisa = texto.index("- analisa:")
    assert valida < paralelo < analisa
    assert "jobs/${job_de_validacao}" in texto
    # A transcrição e a leitura da tela só rodam com o Job em `analisando`.
    assert texto.index('estado.stringValue == "analisando"') < paralelo


def test_transcricao_e_leitura_da_tela_rodam_em_paralelo_nos_jobs_com_gpu() -> None:
    texto = _texto()

    paralelo = _paralelo(texto)
    assert "parallel:" in paralelo and "branches:" in paralelo
    transcricao = _ramo(texto, "ramo_da_transcricao")
    leitura = _ramo(texto, "ramo_da_leitura_da_tela")
    assert "job_gpu: ${job_de_transcricao_gpu}" in transcricao
    assert "job_cpu: ${job_de_transcricao}" in transcricao
    assert "job_gpu: ${job_de_ocr_gpu}" in leitura
    assert "job_cpu: ${job_de_ocr}" in leitura
    # Os dois ramos mantêm o próprio registro de etapa e o próprio código de falha.
    assert "etapa: transcricao" in transcricao and "etapa: leitura_da_tela" in leitura
    assert "codigo_da_falha: transcricao_falhou" in transcricao
    assert "codigo_da_falha: ocr_falhou" in leitura
    # Só o paralelo chama os Jobs de GPU, e a análise vem depois dele.
    assert texto.count("job_gpu: ${job_de_transcricao_gpu}") == 1
    assert texto.count("job_gpu: ${job_de_ocr_gpu}") == 1
    assert texto.index("- roda_em_paralelo:") < texto.index("- analisa:")


def test_falha_de_um_ramo_derruba_o_job_e_a_analise_nao_comeca() -> None:
    texto = _texto()

    paralelo = _paralelo(texto)
    # O ramo que não falhou termina e registra o fim; a falha sobe depois dos dois.
    assert "exception_policy: continueAll" in paralelo
    excecao = paralelo[paralelo.index("        except:") :]
    assert "raise: $${e}" in excecao
    # A falha de cada ramo derruba o Job com o código da etapa, na releitura segura.
    etapa = _subworkflow(texto, "etapa_com_gpu")
    assert "falhou_na_execucao: true" in etapa
    assert "stringValue: $${codigo_da_falha}" in etapa
    assert "stringValue: falhou" in etapa
    assert etapa.rstrip().count("raise: $${e}") == 1
    # Falhou o paralelo, o fluxo não cai em nenhum passo: a execução termina com erro.
    assert "next:" not in excecao


def test_falha_de_cada_ramo_nao_sobrescreve_outro_estado() -> None:
    texto = _texto()

    etapa = _subworkflow(texto, "etapa_com_gpu")
    releitura = etapa.index("documents.get")
    condicao = etapa.index('estado.stringValue != "analisando"')
    patch = etapa.index("documents.patch")
    assert releitura < condicao < patch
    assert "updateTime: $${durante.updateTime}" in etapa
    assert "raise: $${e}" in etapa


def test_ramo_roda_o_job_com_override_de_job_id() -> None:
    texto = _texto()

    roda = _subworkflow(texto, "roda_o_job_com_gpu")
    assert roda.count("googleapis.run.v2.projects.locations.jobs.run") == 2
    assert roda.count("name: JOB_ID") == 2 and roda.count("value: $${job_id}") == 2
    assert "locations/${regiao_gpu}/jobs/" in roda
    assert "locations/${regiao}/jobs/" in roda


def test_job_de_ocr_no_main_tf_sem_internet_e_na_rede_da_validacao() -> None:
    main = MAIN.read_text()

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
    main = MAIN.read_text()

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
    main = MAIN.read_text()

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
    main = MAIN.read_text()

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
    main = MAIN.read_text()
    texto = _texto()
    passos = {
        "valida": ("validacao", "- valida:", "- le_o_job:"),
        "analisa": ("analise", "- analisa:", "- inicia_identificacao:"),
        "identifica": ("identificacao", "- identifica:", "- inicia_quadros_chave:"),
        "tira_os_quadros": ("quadros", "- tira_os_quadros:", "- indexa:"),
        "indexa": ("indexacao", "- indexa:", "- fim:"),
    }
    for nome, (job, de, ate) in passos.items():
        passo = texto[texto.index(de) : texto.index(ate)]
        conector = re.search(r"connector_params:\s+timeout: (\d+)", passo)
        assert conector is not None, nome
        assert int(conector.group(1)) > _timeout_do_job(main, job), nome

    # Os Jobs de GPU e os de CPU do paralelo: o timeout vem no argumento de cada ramo.
    ramos = {
        "ramo_da_transcricao": ("transcricao_gpu", "transcricao"),
        "ramo_da_leitura_da_tela": ("ocr_gpu", "ocr"),
    }
    for ramo, (gpu, cpu) in ramos.items():
        texto_do_ramo = _ramo(texto, ramo)
        for sufixo, job in (("gpu", gpu), ("cpu", cpu)):
            achado = re.search(rf"timeout_{sufixo}: (\d+)", texto_do_ramo)
            assert achado is not None, (ramo, sufixo)
            assert int(achado.group(1)) > _timeout_do_job(main, job), (ramo, sufixo)
    # O subworkflow passa o argumento ao conector, sem valor fixo.
    roda = _subworkflow(texto, "roda_o_job_com_gpu")
    assert "timeout: $${timeout_gpu}" in roda and "timeout: $${timeout_cpu}" in roda


def _timeout_do_job(main: str, job: str) -> int:
    recurso = main[main.index(f'resource "google_cloud_run_v2_job" "{job}"') :]
    recurso = recurso[: recurso.index("\n}\n")]
    achado = re.search(r'timeout\s*=\s*"(\d+s)"', recurso)
    assert achado is not None, job
    return _segundos(achado.group(1))


def test_nenhum_comentario_da_infra_fala_em_ate_10_min() -> None:
    infra = MODULO
    for arquivo in (infra / "main.tf", DEFINICAO):
        assert "até 10 min" not in arquivo.read_text()


ETAPAS = [
    ("valida", "validacao"),
    ("analisa", "analise"),
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

    marcas = texto[texto.index("\nmarca_inicio:") : texto.index("\netapa_com_gpu:")]
    assert '"etapas." + etapa' in marcas
    assert 'etapas." + etapa + ".fim"' in marcas
    assert "resultado" in marcas
    assert '"estado"' not in marcas and "estado]" not in marcas
    # Um objeto sem Job não cria documento, e a medição nunca derruba o processamento.
    assert marcas.count("exists: true") == 2
    assert "sys.log" in marcas


def test_passos_depois_da_analise_so_comecam_com_o_job_concluido() -> None:
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


def test_ordem_nova_identificacao_quadros_indexacao() -> None:
    texto = _texto()

    ordem = [
        "- analisa:",
        "- identifica:",
        "- tira_os_quadros:",
        "- indexa:",
        "- fim:",
    ]
    posicoes = [texto.index(passo) for passo in ordem]
    assert posicoes == sorted(posicoes)
    for job in ("identificacao",):
        inicio = re.search(
            rf"call: marca_inicio\s+args:\s+job_id: \$\$\{{job_id\}}\s+etapa: {job}\n",
            texto,
        )
        assert inicio, job
        assert (
            f"jobs/${{job_de_{job}}}"
            in texto[inicio.end() :].split("- tira_os_quadros:")[0]
        )
    # O nome de cada Job vem do main.tf pelo templatefile.
    main = MAIN.read_text()
    for job in ("identificacao",):
        assert f"job_de_{job}" in main


@pytest.mark.parametrize(
    ("passo", "etapa", "seguinte"),
    [
        ("identifica", "identificacao", "inicia_quadros_chave"),
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


def test_depois_da_identificacao_nenhum_desvio_pula_os_quadros_nem_a_indexacao() -> (
    None
):
    texto = _texto()

    # Do início da identificação até a indexação, todo `next:` cai num passo desse
    # trecho (ou adiante), e nada derruba a execução: uma falha ali não impede o resto.
    trecho = texto[texto.index("- inicia_identificacao:") : texto.index("- indexa:")]
    passos = set(re.findall(r"^\s+- (\w+):\n", trecho, re.MULTILINE))
    for destino in re.findall(r"next: (\w+)", trecho):
        assert destino in passos or destino in {"inicia_indexacao"}, destino
    assert "raise:" not in trecho and "return:" not in trecho


def test_etapas_dos_jobs_que_gravam_o_proprio_resultado_nao_sao_regravadas_como_concluida() -> (
    None
):
    texto = _texto()

    assert "etapa: identificacao\n          falhou_na_execucao: false" not in texto


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
        "job_de_quadros",
    ):
        assert antes not in daqui


def test_cada_etapa_de_partida_cai_no_inicio_da_propria_etapa() -> None:
    texto = _texto()

    assert _destino(texto, "quadros_chave") == "inicia_quadros_chave"
    assert _destino(texto, "identificacao") == "inicia_identificacao"


def test_a_api_so_inicia_execucoes_do_workflow_e_sabe_qual_e() -> None:
    main = MAIN.read_text()

    web = main[main.index("papeis_no_projeto = {") :].split("validacao ")[0]
    assert '"roles/workflows.invoker"' in web
    assert "workflows.admin" not in main and "workflows.editor" not in main
    # O mesmo nome no workflow e na web, pelo local (a referência ao recurso fecha um ciclo).
    assert "name            = local.workflow_validacao" in main
    assert "value = local.workflow_validacao" in main
    assert 'name  = "WORKFLOW_VALIDACAO"' in main
    assert 'name  = "WORKFLOW_REGIAO"' in main


def _job_do_main_tf(nome: str) -> str:
    main = MAIN.read_text()
    return main[main.index(f'resource "google_cloud_run_v2_job" "{nome}"') :].split(
        "\nresource "
    )[0]


def test_job_de_identificacao_sem_internet_com_a_imagem_do_ffmpeg() -> None:
    nome, modulo = "identificacao", "identificacao_job"
    main = MAIN.read_text()
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

    assert "var.limite_de_pessoas_do_modelo_forte" in ident
    assert 'name  = "LIMITE_DE_PESSOAS_DO_MODELO_FORTE"' in ident
    assert 'local.buckets["referencias"]' not in ident


def test_contas_e_papeis_dos_jobs_novos_sao_so_os_combinados() -> None:
    main = MAIN.read_text()

    contas = main.split("for_each     = toset([")[1].split("])")[0]
    assert '"identificacao"' in contas
    assert re.search(
        r'\n\s+identificacao\s+= \["roles/datastore.user", local.papel_vertex_predicao\]',
        main,
    )
    assert re.search(
        r'identificacao = \{ aceitos = "roles/storage.objectViewer", '
        r'decupagens = "roles/storage.objectUser" \}',
        main,
    )


def test_o_bucket_das_referencias_nao_tem_regra_de_ciclo_de_vida() -> None:
    main = MAIN.read_text()
    bucket = main[main.index('resource "google_storage_bucket" "mam"') :].split(
        "\nresource "
    )[0]

    assert "lifecycle_rule" not in bucket
    assert "prazo_dos_palpites_dias" not in main


def test_as_etapas_de_referencias_e_comparacao_sairam_da_infra() -> None:
    main = MAIN.read_text()

    for resto in ("serpapi", "mam-referencias", "mam-comparacao", "SerpAPI"):
        assert resto not in main, resto
    assert "secretAccessor" not in main
    assert "job_de_referencias" not in main and "job_de_comparacao" not in main


def test_a_api_le_e_apaga_as_fotos_de_referencia() -> None:
    # Lê para assinar o link do nome; apaga as fotos de rosto no envio da pessoa à lixeira (#151).
    main = MAIN.read_text()

    assert re.search(
        r'web = \{[^}\n]*referencias = "roles/storage.objectUser"[^}\n]*\}', main
    )
    servico = main.split('resource "google_cloud_run_v2_service" "web"')[1].split(
        "\nresource "
    )[0]
    assert 'name  = "BUCKET_REFERENCIAS"' in servico
    assert 'local.buckets["referencias"]' in servico


def test_quem_regrava_o_que_ja_gravou_pode_sobrescrever_no_main_tf() -> None:
    # O reprocessamento escolhido (#235) refaz etapas de um Job concluído: sobrescrever
    # exige `storage.objects.delete`, que o `objectCreator` não tem.
    main = MAIN.read_text()

    def papel(conta: str, bucket: str) -> str:
        achado = re.search(
            rf"^\s+{conta} = \{{.*?\b{bucket} = \"([\w./]+)\"", main, re.MULTILINE
        )
        assert achado, (conta, bucket)
        return achado.group(1)

    for conta, bucket in [
        ("analise", "decupagens"),
        ("analise", "aceitos"),
        ("web", "aceitos"),
        ("quadros", "decupagens"),
        ("identificacao", "decupagens"),
    ]:
        assert papel(conta, bucket) == "roles/storage.objectUser", (conta, bucket)


def test_reprocessar_a_transcricao_roda_os_dois_ramos() -> None:
    texto = _texto()

    assert _destino(texto, "transcricao") == "roda_em_paralelo"
    atribuicoes = texto[texto.index("- tira_o_id_do_reprocessamento:") :].split(
        "- parte_da_etapa:"
    )[0]
    assert "roda_a_transcricao: true" in atribuicoes
    assert "roda_a_leitura_da_tela: true" in atribuicoes
    # Cada ramo só roda se a sua variável deixa.
    assert "condition: $${roda_a_transcricao}" in _ramo(texto, "ramo_da_transcricao")
    assert "condition: $${roda_a_leitura_da_tela}" in _ramo(
        texto, "ramo_da_leitura_da_tela"
    )


def test_reprocessar_a_leitura_da_tela_roda_so_o_ocr_e_ele_mostra_a_etapa() -> None:
    texto = _texto()

    assert _destino(texto, "leitura_da_tela") == "so_a_leitura_da_tela"
    passo = _depois_de(texto, "so_a_leitura_da_tela").split("- roda_em_paralelo:")[0]
    assert "roda_a_transcricao: false" in passo
    assert "next: roda_em_paralelo" in passo
    # Sozinha, a leitura da tela é a etapa atual; com a transcrição, quem mostra é ela.
    assert "mostra_a_etapa: $${not roda_a_transcricao}" in _ramo(
        texto, "ramo_da_leitura_da_tela"
    )
    assert "mostra_a_etapa: true" in _ramo(texto, "ramo_da_transcricao")


def test_etapas_em_paralelo_nao_se_atropelam_no_etapa_atual() -> None:
    texto = _texto()

    inicio = _subworkflow(texto, "marca_inicio")
    fim = _subworkflow(texto, "marca_fim")
    assert "params: [job_id, etapa, mostra_a_etapa: true]" in inicio
    assert "falhou_na_execucao, limpa_a_etapa: true," in fim
    etapa = _subworkflow(texto, "etapa_com_gpu")
    assert etapa.count("limpa_a_etapa: false") == 2
    # Só a falha do paralelo, depois dos dois ramos, limpa o campo.
    assert "call: limpa_a_etapa_atual" in _paralelo(texto)
    assert "etapa_atual" in _subworkflow(texto, "limpa_a_etapa_atual")


def test_espera_total_vem_de_uma_variavel_do_main_tf_com_27_minutos() -> None:
    main = MAIN.read_text()

    variavel = main.split('variable "espera_gpu_minutos"')[1].split("\n}")[0]
    assert "default     = 27" in variavel
    assert re.search(r"gpu_espera_total_s\s+=\s+var\.espera_gpu_minutos \* 60", main)
    texto = _texto()
    assert texto.count("${gpu_espera_total_s}") >= 1
    for nome in ("gpu_espera_s", "gpu_fator_da_espera", "gpu_espera_maxima_s"):
        assert re.search(rf"{nome}\s+= var\.{nome}", main), nome
        assert "${" + nome + "}" in texto, nome


def test_so_a_falta_de_gpu_ou_de_cota_tenta_de_novo_e_o_plano_b_vem_depois() -> None:
    texto = _texto()

    roda = _subworkflow(texto, "roda_o_job_com_gpu")
    # Falha dentro do contêiner: marca a GPU e sobe, sem espera nem plano B.
    falha = roda.index("falha_dentro_do_conteiner:")
    espera = roda.index("ainda_cabe_esperar:")
    assert falha < espera
    dentro = roda[falha:espera]
    assert "condition: $${not faltou_gpu}" in dentro
    assert "raise: $${erro_da_gpu}" in dentro
    assert "sys.sleep" not in dentro and "plano_b" not in dentro
    # O que conta como falta de GPU ou de cota, e o que nunca conta.
    assert "codigo_http == 429" in roda
    assert "quota|capacity" in roda
    assert "exit[(]|exit code|container called" in roda


def test_as_esperas_crescem_ate_o_teto_e_nao_passam_da_espera_total() -> None:
    texto = _texto()

    roda = _subworkflow(texto, "roda_o_job_com_gpu")
    assert "esperado + espera <= ${gpu_espera_total_s}" in roda
    assert "esperado: $${esperado + espera}" in roda
    assert "math.min(espera * ${gpu_fator_da_espera}, ${gpu_espera_maxima_s})" in roda
    # A ordem: decide se cabe, avisa, espera, cresce e tenta de novo.
    ordem = [
        "ainda_cabe_esperar:",
        "registra_a_nova_tentativa:",
        "espera_a_gpu:",
        "cresce_a_espera:",
    ]
    posicoes = [roda.index(passo) for passo in ordem]
    assert posicoes == sorted(posicoes)
    assert "next: conta_a_tentativa" in roda[roda.index("cresce_a_espera:") :]
    # O log diz por que cada tentativa falhou.
    assert "sys.log" in roda and "mensagem" in roda


def _tentativas(total: int, inicio: int, fator: int, teto: int) -> int:
    """Espelha a conta do Workflows: quantas vezes o Job com GPU é pedido."""
    tentativas, espera, esperado = 1, inicio, 0
    while esperado + espera <= total:
        esperado += espera
        espera = min(espera * fator, teto)
        tentativas += 1
    return tentativas


def test_a_conta_das_tentativas_dos_valores_propostos_e_de_uma_espera_menor() -> None:
    main = MAIN.read_text()

    def padrao(nome: str) -> int:
        variavel = main.split(f'variable "{nome}"')[1].split("\n}")[0]
        return int(re.search(r"default\s+=\s+(\d+)", variavel).group(1))  # type: ignore[union-attr]

    inicio = padrao("gpu_espera_s")
    fator = padrao("gpu_fator_da_espera")
    teto = padrao("gpu_espera_maxima_s")
    total = padrao("espera_gpu_minutos") * 60

    # 60, 120 e seis esperas de 240 s: 9 tentativas em 27 minutos.
    assert _tentativas(total, inicio, fator, teto) == 9
    # Uma espera total menor dá menos tentativas; com zero, uma só antes do plano B.
    assert _tentativas(5 * 60, inicio, fator, teto) == 3
    assert _tentativas(0, inicio, fator, teto) == 1


def test_esgotada_a_espera_o_ramo_roda_o_job_em_cpu_e_registra_cpu() -> None:
    texto = _texto()

    roda = _subworkflow(texto, "roda_o_job_com_gpu")
    plano_b = roda[roda.index("registra_o_plano_b:") :]
    assert "plano B" in plano_b and "sys.log" in plano_b
    assert plano_b.index("dispositivo: cpu") < plano_b.index(
        "googleapis.run.v2.projects.locations.jobs.run"
    )
    assert "tentativas: $${tentativas}" in plano_b
    assert "locations/${regiao}/jobs/" in plano_b
    assert "return: cpu" in plano_b
    # O plano B não tem `try`: a falha dele derruba a etapa como a de hoje.
    assert "try:" not in plano_b


def test_sucesso_na_gpu_registra_gpu_e_as_tentativas() -> None:
    texto = _texto()

    roda = _subworkflow(texto, "roda_o_job_com_gpu")
    sucesso = roda[
        roda.index("registra_o_sucesso_na_gpu:") : roda.index(
            "registra_a_nova_tentativa:"
        )
    ]
    assert "dispositivo: gpu" in sucesso and "tentativas: $${tentativas}" in sucesso
    assert "return: gpu" in sucesso
    marca = _subworkflow(texto, "marca_dispositivo")
    assert 'etapas." + etapa + ".dispositivo"' in marca
    assert 'etapas." + etapa + ".tentativas_gpu"' in marca
    assert "integerValue" in marca
    # Medição: a falha da gravação só vai ao log.
    assert "except:" in marca and "sys.log" in marca


def test_falta_de_gpu_le_o_motivo_da_operacao_e_nao_confunde_permissao() -> None:
    texto = _texto()

    roda = _subworkflow(texto, "roda_o_job_com_gpu")
    # A execução que falhou vem como OperationError: o motivo fica na operação.
    assert '["operation", "error", "message"]' in roda
    # A mesma conta do teste depois da publicação (scripts/testar-jobs-gpu.sh).
    assert "insufficient (gpu|resources|capacity)" in roda
    assert "|insufficient|" not in roda
    script = (Path(__file__).parents[2] / "scripts" / "testar-jobs-gpu.sh").read_text()
    assert "insufficient (gpu|resources|capacity)" in script


def test_ramo_que_terminou_bem_nao_vira_falhou_pela_falha_do_outro() -> None:
    texto = _texto()

    fim = _subworkflow(texto, "marca_fim")
    assert "confere_o_estado: true" in fim
    assert (
        '(confere_o_estado and documento_da_etapa.fields.estado.stringValue == "falhou")'
        in fim
    )
    etapa = _subworkflow(texto, "etapa_com_gpu")
    encerra = etapa[etapa.index("- encerra_a_etapa:") :]
    assert "confere_o_estado: false" in encerra


def test_marcar_a_falha_rele_o_job_se_o_outro_ramo_gravou_no_meio() -> None:
    texto = _texto()

    etapa = _subworkflow(texto, "etapa_com_gpu")
    marca = etapa[
        etapa.index("- marca_a_etapa_como_falha:") : etapa.index(
            "- encerra_a_etapa_com_falha:"
        )
    ]
    assert "try:" in marca and "except:" in marca
    assert "next: rele_antes_da_falha" in marca
    assert "releituras < 5" in marca
    # Esgotadas as releituras, o erro original ainda sobe.
    assert "raise: $${e}" in etapa[etapa.index("- encerra_a_etapa_com_falha:") :]


def test_dispositivo_so_e_gravado_na_etapa_iniciada() -> None:
    texto = _texto()

    marca = _subworkflow(texto, "marca_dispositivo")
    confere = marca.index('["etapas", "mapValue", "fields", etapa]) == null')
    assert confere < marca.index("documents.patch")
    assert "next: fim_do_dispositivo" in marca


def _passo_do_inventario() -> str:
    texto = _texto()
    return texto[
        texto.index("- inicia_inventario_de_objetos:") : texto.index(
            "- inicia_indexacao:"
        )
    ]


def test_o_inventario_de_objetos_fica_entre_os_quadros_chave_e_a_indexacao() -> None:
    texto = _texto()

    assert _destino(texto, "quadros_chave") == "inicia_quadros_chave"
    assert (
        texto.index("- encerra_quadros_chave:")
        < texto.index("- inicia_inventario_de_objetos:")
        < texto.index("- encerra_inventario_de_objetos:")
        < texto.index("- inicia_indexacao:")
    )
    # A falha dos quadros-chave não pula o inventário; a do inventário não pula a indexação.
    quadros = texto[
        texto.index("- tira_os_quadros:") : texto.index("- encerra_quadros")
    ]
    assert "next: inicia_inventario_de_objetos" in quadros
    assert 'etapa_inicial == "inventario_de_objetos"' in texto
    assert "etapa: inventario_de_objetos" in _passo_do_inventario()


def test_o_motor_florence_roda_a_gpu_sem_plano_b_e_depois_o_job_em_cpu() -> None:
    passo = _passo_do_inventario()

    assert '"${motor_objetos}" == "florence"' in passo
    florence = passo[
        passo.index("- roda_o_florence:") : passo.index("- roda_o_inventario:")
    ]
    assert "call: roda_o_job_com_gpu" in florence
    assert "job_gpu: ${job_de_objetos_gpu}" in florence
    assert "job_cpu" not in florence
    assert "timeout_gpu: 11100" in florence
    cpu = passo[passo.index("- roda_o_inventario:") :]
    assert "jobs/${job_de_inventario}" in cpu
    assert "timeout: 3900" in cpu
    # O motor gemini pula o Job com GPU.
    assert passo.index("next: roda_o_florence") < passo.index("next: roda_o_inventario")


def test_a_falha_do_inventario_marca_a_etapa_e_segue_para_a_indexacao() -> None:
    passo = _passo_do_inventario()

    assert passo.count("falhou_na_execucao: true") == 2
    assert passo.count("next: inicia_indexacao") == 2


def test_sem_job_em_cpu_a_gpu_esgotada_repassa_a_falha() -> None:
    texto = _texto()
    funcao = texto[texto.index("roda_o_job_com_gpu:\n") :]

    assert (
        "params: [job_id, etapa, job_gpu, timeout_gpu, job_cpu: null, timeout_cpu: null]"
        in funcao
    )
    assert "$${job_cpu == null}" in funcao
    assert "raise: $${erro_final}" in funcao
    assert funcao.index("raise: $${erro_final}") < funcao.index("- registra_o_plano_b:")
    # Esgotada a espera, o fluxo passa pela conferência antes do plano B.
    cabe = funcao[
        funcao.index("- ainda_cabe_esperar:") : funcao.index("- registra_o_sucesso")
    ]
    assert cabe.rstrip().endswith("next: confere_se_ha_plano_b")


def test_a_definicao_renderizada_e_yaml_valido() -> None:
    # O Workflows lê YAML: uma expressão sem aspas com ": " dentro vira chave e valor, e a
    # publicação falha (deploy de 2026-11-03). Renderiza como o templatefile e abre.
    renderizado = re.sub(r"(?<!\$)\$\{\w+\}", "x", _texto()).replace("$${", "${")
    assert isinstance(yaml.safe_load(renderizado), dict)


# Escopo das variáveis, como o Workflows confere ao publicar: uma variável criada dentro de
# um `except` ou de um `for` só existe ali, e usá-la fora falha a publicação ("symbol ...
# is neither a variable nor a sub-workflow name", deploy de 2026-11-03).
_MODULOS = {"sys", "text", "map", "math", "json", "list", "time", "base64", "hash"}
_MODULOS |= {"uuid", "events", "http", "retry", "googleapis", "experimental"}
_PALAVRAS = {"and", "or", "not", "in", "true", "false", "null"}
_SALTOS = {"end", "continue", "break"}


def _expressoes(valor: Any) -> list[str]:
    if isinstance(valor, dict):
        return [e for v in valor.values() for e in _expressoes(v)]
    if isinstance(valor, list):
        return [e for v in valor for e in _expressoes(v)]
    achadas = []
    for inicio in re.finditer(r"\$\{", str(valor) if isinstance(valor, str) else ""):
        i, profundidade = inicio.end(), 1
        while i < len(valor) and profundidade:
            profundidade += {"{": 1, "}": -1}.get(valor[i], 0)
            i += 1
        achadas.append(valor[inicio.end() : i - 1])
    return achadas


def _simbolos(expressao: str) -> set[str]:
    sem_texto = re.sub(r'"(?:[^"\\]|\\.)*"', '""', expressao)
    nomes = set()
    for m in re.finditer(r"(?<![\w.])([A-Za-z_]\w*)", sem_texto):
        nome, resto = m.group(1), sem_texto[m.end() :].lstrip()
        modulo = nome in _MODULOS and resto.startswith(".")
        if nome not in _PALAVRAS and not resto.startswith("(") and not modulo:
            nomes.add(nome)
    return nomes


def _definidos(passos: list[Any] | None) -> set[str]:
    """O que os passos criam no escopo deles, sem entrar no `except` nem no `for`."""
    nomes: set[str] = set()
    for passo in passos or []:
        ((_, corpo),) = passo.items()
        for atribuicao in corpo.get("assign") or []:
            nomes |= {re.split(r"[\[.]", chave)[0] for chave in atribuicao}
        tentativa = corpo.get("try") or {}
        for fonte in (corpo, tentativa):
            if "result" in fonte:
                nomes.add(fonte["result"])
        nomes |= _definidos(tentativa.get("steps")) | _definidos(corpo.get("steps"))
        for ramo in corpo.get("switch") or []:
            nomes |= _definidos(ramo.get("steps"))
    return nomes


def _nomes_dos_passos(passos: list[Any] | None) -> set[str]:
    nomes: set[str] = set()
    for passo in passos or []:
        ((nome, corpo),) = passo.items()
        nomes.add(nome)
        nomes |= _nomes_dos_passos(corpo.get("steps"))
        for ramo in corpo.get("switch") or []:
            nomes |= _nomes_dos_passos(ramo.get("steps"))
    return nomes


def _problemas(
    passos: list[Any] | None, escopo: set[str], alvos: set[str], onde: str
) -> list[str]:
    achados = []
    for passo in passos or []:
        ((nome, corpo),) = passo.items()
        blocos = ("for", "try", "except", "steps", "switch")
        proprio = {k: v for k, v in corpo.items() if k not in blocos}
        ramos = corpo.get("switch") or []
        condicoes = [{k: v for k, v in r.items() if k != "steps"} for r in ramos]
        laco = {k: v for k, v in (corpo.get("for") or {}).items() if k != "steps"}
        for expressao in _expressoes([proprio, condicoes, laco]):
            for simbolo in _simbolos(expressao) - escopo:
                achados.append(f"{onde}/{nome}: {simbolo!r} fora do escopo")
        for salto in [corpo.get("next")] + [r.get("next") for r in ramos]:
            if salto and salto not in alvos | _SALTOS:
                achados.append(f"{onde}/{nome}: next {salto!r} não existe")
        for ramo in ramos:
            achados += _problemas(ramo.get("steps"), escopo, alvos, onde)
        achados += _problemas(corpo.get("steps"), escopo, alvos, onde)
        tentativa = corpo.get("try") or {}
        if "steps" in tentativa:
            achados += _problemas(tentativa["steps"], escopo, alvos, onde)
        elif tentativa:
            achados += _problemas([{nome: tentativa}], escopo, alvos, onde)
        for bloco, locais in (
            (corpo.get("except"), ["as"]),
            (corpo.get("for"), ["value", "index"]),
        ):
            if bloco:
                interno = bloco.get("steps")
                local = escopo | {bloco[k] for k in locais if k in bloco}
                achados += _problemas(
                    interno,
                    local | _definidos(interno),
                    alvos | _nomes_dos_passos(interno),
                    onde,
                )
    return achados


def test_toda_variavel_usada_existe_no_escopo_do_passo() -> None:
    definicao = _definicao()
    achados = []
    for nome, sub in definicao.items():
        params = {
            p if isinstance(p, str) else next(iter(p)) for p in sub.get("params", [])
        }
        escopo = params | _definidos(sub["steps"]) | set(definicao)
        achados += _problemas(
            sub["steps"], escopo, _nomes_dos_passos(sub["steps"]), nome
        )
    assert achados == []


def test_list_concat_anexa_um_item_e_nao_uma_lista() -> None:
    # `list.concat(l, ["x"])` anexa a lista inteira como um item: o updateMask do
    # Firestore recebe uma lista dentro da lista e o passo cai (dev, 2026-11-03).
    assert re.findall(r"list\.concat\([^,]+,\s*\[", _texto()) == []


def test_conta_da_orquestracao_grava_log_do_sys_log() -> None:
    assert "call: sys.log" in _texto()
    linha = re.search(r"^\s*orquestracao\s*=\s*\[.*\]$", MAIN.read_text(), re.MULTILINE)
    assert linha and '"roles/logging.logWriter"' in linha.group(0)


def _definicao() -> dict[str, Any]:
    renderizado = re.sub(r"(?<!\$)\$\{\w+\}", "1", _texto()).replace("$${", "${")
    definicao: dict[str, Any] = yaml.safe_load(renderizado)
    return definicao


def test_erro_sem_tratamento_marca_o_job_interrompido_e_sobe() -> None:
    # Sem isto, o Job fica em `analisando` ("Decupando") para sempre (dev, 2026-11-03).
    definicao = _definicao()
    passos = [next(iter(p.values())) for p in definicao["main"]["steps"]]
    rodada = next(p for p in passos if "try" in p)
    assert rodada["try"]["call"] == "processa"
    tratamento = [next(iter(p.values())) for p in rodada["except"]["steps"]]
    marcacao = [next(iter(p.values())) for p in tratamento[0]["try"]["steps"]]
    assert marcacao[0]["call"] == "marca_interrompido"
    assert marcacao[-1]["call"] == "sys.log" and marcacao[-1]["args"]["data"] == "${e}"
    assert tratamento[-1] == {"raise": "${e}"}
    # O id sai antes do try, dos dois formatos: o reprocessamento e o Eventarc.
    texto = _subworkflow(_texto(), "main")
    assert texto.index('map.get(evento, "job_id")') < texto.index("call: processa")
    assert "job_do_evento: $${evento.data.name}" in texto


def test_marca_interrompido_so_derruba_job_em_andamento() -> None:
    marca = _subworkflow(_texto(), "marca_interrompido")
    assert '["aguardando_upload", "validando", "analisando"]' in marca
    # A etapa já fechada (a do paralelo, que não limpa o `etapa_atual`) não é regravada.
    assert '"fim", "timestampValue"]) == null' in marca
    assert "stringValue: processamento_interrompido" in marca
    assert "updateTime: $${interrompido.updateTime}" in marca
    # A etapa em andamento fecha como `falhou`, para o reprocessar recomeçar dali.
    assert "call: marca_fim" in marca and "falhou_na_execucao: true" in marca


def test_toda_falha_que_o_workflow_grava_chama_o_aviso_do_fim_logo_depois() -> None:
    texto = _texto()

    patches = [
        m.start()
        for m in re.finditer(r"documents\.patch", texto)
        if "stringValue: falhou" in texto[m.start() : m.start() + 900]
    ]
    assert len(patches) == 4
    for inicio in patches:
        assert "call: avisa_o_fim" in texto[inicio : inicio + 2400]
    assert 'in ["cancelado", "falhou"]' in texto


def test_o_aviso_do_fim_roda_o_job_com_job_id_e_o_erro_dele_so_vai_ao_log() -> None:
    texto = _texto()

    aviso = texto[texto.index("\navisa_o_fim:") : texto.index("\nmarca_interrompido:")]
    assert "jobs/${job_de_fim}" in aviso
    assert "name: JOB_ID" in aviso and "value: $${job_id}" in aviso
    assert "except:" in aviso and "sys.log" in aviso and "raise" not in aviso


def test_o_job_do_aviso_do_fim_e_o_que_o_workflow_roda() -> None:
    fim = (MODULO / "fim_do_job.tf").read_text()

    assert 'resource "google_cloud_run_v2_job" "fim"' in fim
    assert '"api.fim_do_job"' in fim
    for variavel in ("PUBSUB_TOPICO_EVENTOS", "PUBSUB_TOPICO_USO", "GCP_PROJECT_ID"):
        assert f'"{variavel}"' in fim
    assert (
        "job_de_fim             = google_cloud_run_v2_job.fim.name" in MAIN.read_text()
    )
    assert "google_cloud_run_v2_job.fim.name" in fim  # o papel de rodar, só para ele
