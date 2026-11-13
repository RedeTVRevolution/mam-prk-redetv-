"""Dados do vídeo no BigQuery e Firestore que só a purga apaga (#504)."""

from collections.abc import Mapping

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from api.copia_bigquery import ConfigDoBigQuery, Transporte, parametro, transporte_http
from api.nuvem import COLECAO_DA_REVISAO, TiposDeObjetoFirestore
from api.texto_como_dado import id_conferido


def executar(
    config: ConfigDoBigQuery, transporte: Transporte, consulta: str, job_id: str
) -> int:
    """Só confirma o apagamento quando o BigQuery confirma o término sem erro."""
    resposta = transporte(
        {
            "query": consulta,
            "useLegacySql": False,
            "location": config.regiao,
            "timeoutMs": 120_000,
            "queryParameters": [parametro("job_id", job_id)],
        }
    )
    if not resposta.get("jobComplete") or resposta.get("errors"):
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
        tabelas = [c.tabela]
        if antiga := ambiente.get("BIGQUERY_TABELA_ANTIGA"):
            tabelas.append(antiga)
        tabelas.append(ambiente["BIGQUERY_TABELA_DE_REVISAO"])
        apagamentos = "\n".join(
            f"DELETE FROM `{prefixo}.{tabela}` WHERE job_id = @job_id;"
            for tabela in tabelas
        )
        # A trava antecede o marcador e conflita com a consulta agendada. O INSERT direto
        # dispensa a entrega pelo Pub/Sub e não perde a falha no log.
        self._consulta = f"""
BEGIN TRANSACTION;
DELETE FROM {jobs} WHERE id = @job_id;
INSERT INTO {eventos} (id, tipo, quando, quem_tipo, quem_id, job_id)
SELECT CONCAT('purga:', @job_id), 'purga', CURRENT_TIMESTAMP(), 'sistema', 'purga', @job_id
WHERE NOT EXISTS (SELECT 1 FROM {eventos} WHERE tipo = 'purga' AND job_id = @job_id);
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
