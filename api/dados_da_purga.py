"""Dados do vídeo no BigQuery e Firestore que só a purga apaga (#504)."""

from collections.abc import Mapping

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from api.copia_bigquery import (
    PRAZO_CURTO,
    ConfigDoBigQuery,
    Transporte,
    executar_dml,
    parametro,
    transporte_http,
)
from api.nuvem import COLECAO_DA_REVISAO, TiposDeObjetoFirestore
from api.texto_como_dado import id_conferido


def executar(
    config: ConfigDoBigQuery, transporte: Transporte, consulta: str, job_id: str
) -> int:
    """Só confirma o apagamento quando o BigQuery confirma o término sem erro."""
    resposta = executar_dml(
        transporte,
        config.regiao,
        consulta,
        [parametro("job_id", job_id)],
        PRAZO_CURTO,
        descricao=f"purga de {job_id} no BigQuery",
        mensagem_do_prazo=f"purga de {job_id} no BigQuery não confirmada",
    )
    if resposta.get("errors"):
        raise RuntimeError(f"purga de {job_id} no BigQuery não confirmada")
    return int(resposta.get("numDmlAffectedRows", 0))


class DadosDaPurga:
    def __init__(
        self,
        cliente: firestore.Client,
        ambiente: Mapping[str, str],
        transporte: Transporte,
    ) -> None:
        self._config = ConfigDoBigQuery.do_ambiente(ambiente)
        self._transporte = transporte
        c = self._config
        prefixo = f"{c.projeto}.{c.dataset}"
        jobs = f"`{prefixo}.{ambiente['BIGQUERY_TABELA_DE_JOBS']}`"
        eventos = f"`{prefixo}.{ambiente['BIGQUERY_TABELA_DE_EVENTOS']}`"
        tabelas = [
            c.tabela,
            ambiente["BIGQUERY_TABELA_DE_REVISAO"],
            ambiente["BIGQUERY_TABELA_DA_TAXA"],
        ]
        apagamentos = "\n".join(
            f"DELETE FROM `{prefixo}.{tabela}` WHERE job_id = @job_id;"
            for tabela in tabelas
        )
        # O marcador copia a linha do Job antes do DELETE (a transação enxerga o próprio
        # apagamento). Sem linha, ou sem dono completo, vale `sistema`/`purga` e os demais
        # campos vão vazios: ele só barra a reinserção. O INSERT direto dispensa a entrega
        # pelo Pub/Sub e não perde a falha no log; o DELETE do Job conflita com a consulta
        # agendada.
        dono = "j.quem_tipo IS NOT NULL AND j.quem_id IS NOT NULL"
        self._consulta = f"""
BEGIN TRANSACTION;
INSERT INTO {eventos} (id, tipo, quando, quem_tipo, quem_id, job_id, programa, estado,
  duracao_do_video_ms, criado_em)
SELECT CONCAT('purga:', @job_id), 'purga', CURRENT_TIMESTAMP(),
  CASE WHEN {dono} THEN j.quem_tipo ELSE 'sistema' END,
  CASE WHEN {dono} THEN j.quem_id ELSE 'purga' END,
  @job_id,
  CASE WHEN {dono} THEN j.programa END,
  CASE WHEN {dono} THEN j.estado END,
  CASE WHEN {dono} THEN j.duracao_ms END,
  CASE WHEN {dono} THEN j.criado_em END
FROM (SELECT 1) AS x LEFT JOIN {jobs} AS j ON j.id = @job_id
WHERE NOT EXISTS (SELECT 1 FROM {eventos} WHERE tipo = 'purga' AND job_id = @job_id);
DELETE FROM {jobs} WHERE id = @job_id;
{apagamentos}
COMMIT TRANSACTION;
"""
        self._tipos = TiposDeObjetoFirestore(cliente)
        self._revisao = cliente.collection(COLECAO_DA_REVISAO)

    def apagar(self, job_id: str) -> None:
        job_id = id_conferido(job_id)
        executar(self._config, self._transporte, self._consulta, job_id)
        self._tipos.purgar(job_id)
        for doc in self._revisao.where(
            filter=FieldFilter("job_id", "==", job_id)
        ).stream():
            doc.reference.delete()


def dados_do_ambiente(
    cliente: firestore.Client, ambiente: Mapping[str, str]
) -> DadosDaPurga:
    return DadosDaPurga(cliente, ambiente, transporte_http(ambiente["GCP_PROJECT_ID"]))
