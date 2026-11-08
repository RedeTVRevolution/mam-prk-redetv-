"""Pub/Sub dos eventos de uso (#279): esquema, tabela do BigQuery, assinatura e IAM."""

import re
from pathlib import Path

from api.eventos_de_uso import EventoDeUso

MODULO = Path(__file__).parents[2] / "infra" / "modulos" / "mam"
USO = (MODULO / "eventos_de_uso.tf").read_text()
PROTO = (MODULO / "evento_de_uso.proto").read_text()
MAIN = (MODULO / "main.tf").read_text()


def _bloco(texto: str, cabecalho: str) -> str:
    inicio = texto.index(cabecalho)
    return texto[inicio : texto.index("\n}\n", inicio)]


def _campos_do_proto() -> set[str]:
    # Os campos do primeiro nível de `EventoDeUso` têm 2 espaços; os das mensagens
    # aninhadas (Filtro), 4.
    mensagem = _bloco(PROTO, "message EventoDeUso")
    return set(
        re.findall(
            r"^  (?:required|optional|repeated)\s+\S+\s+(\w+)\s*=",
            mensagem,
            re.MULTILINE,
        )
    )


def test_o_proto_tem_uma_mensagem_so_no_primeiro_nivel() -> None:
    # O Pub/Sub recusa o esquema com duas ("Too many message types specified in
    # schema definition") e o `terraform validate` não chama a API: o deploy caía.
    assert re.findall(r"^message (\w+)", PROTO, re.MULTILINE) == ["EventoDeUso"]


def test_os_campos_do_proto_sao_os_do_evento_e_sem_o_texto_da_consulta() -> None:
    assert _campos_do_proto() == set(EventoDeUso.model_fields)
    assert "texto" not in _campos_do_proto()


def test_as_colunas_da_tabela_sao_os_campos_do_evento() -> None:
    tabela = _bloco(USO, 'resource "google_bigquery_table" "eventos_de_uso"')
    colunas = set(
        re.findall(
            r'^    \{ name = "(\w+)"|^      name = "(\w+)", type', tabela, re.MULTILINE
        )
    )
    nomes = {a or b for a, b in colunas}

    assert nomes == set(EventoDeUso.model_fields)


def test_o_topico_usa_o_esquema_em_json_e_a_assinatura_grava_no_bigquery() -> None:
    topico = _bloco(USO, 'resource "google_pubsub_topic" "eventos_de_uso"')
    assinatura = _bloco(USO, 'resource "google_pubsub_subscription" "uso_no_bigquery"')

    assert "google_pubsub_schema.evento_de_uso.id" in topico
    assert 'encoding = "JSON"' in topico
    assert "use_topic_schema = true" in assinatura
    assert "google_bigquery_table.eventos_de_uso" in assinatura
    assert "mam_decupagens" not in USO


def test_quem_publica_so_publica_no_topico_de_uso() -> None:
    bloco = _bloco(USO, 'resource "google_pubsub_topic_iam_member" "publica_uso"')

    assert "roles/pubsub.publisher" in bloco
    assert "google_pubsub_topic.eventos_de_uso.name" in bloco
    assert '"web"' in USO and '"validacao"' in USO and '"analise"' in USO
    assert "google_project_iam_member" not in USO


def test_o_agente_do_pubsub_grava_so_na_tabela() -> None:
    bloco = _bloco(
        USO, 'resource "google_bigquery_table_iam_member" "pubsub_grava_uso"'
    )

    assert "roles/bigquery.dataEditor" in bloco
    assert "roles/bigquery.metadataViewer" in bloco
    assert "local.agente_do_pubsub" in bloco


def test_a_web_e_os_jobs_que_publicam_recebem_o_topico_por_variavel_de_ambiente() -> (
    None
):
    padrao = r'name\s+= "PUBSUB_TOPICO_USO"\s+value\s+= google_pubsub_topic.eventos_de_uso.id'
    blocos = [_bloco(MAIN, 'resource "google_cloud_run_v2_service" "web"')]
    for job in [
        "validacao",
        "transcricao_gpu",
        "ocr_gpu",
        "analise",
    ]:
        blocos.append(_bloco(MAIN, f'resource "google_cloud_run_v2_job" "{job}"'))

    for bloco in blocos:
        assert re.search(padrao, bloco)
