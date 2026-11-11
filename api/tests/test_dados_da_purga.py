"""Purga dos dados, sem serviços de nuvem."""

import sqlite3
from typing import Any
from unittest.mock import Mock

import pytest
from google.cloud import firestore

from api.nuvem import (
    COLECAO_DA_REVISAO,
    COLECAO_DOS_TIPOS_DE_OBJETO,
    COLECAO_DOS_TIPOS_DE_OBJETO_POR_JOB,
)
from api.tests.test_purga import Mundo

AMBIENTE = {
    "GCP_PROJECT_ID": "projeto-teste",
    "BIGQUERY_DATASET": "dados",
    "BIGQUERY_REGIAO": "regiao-teste",
    "BIGQUERY_TABELA": "momentos_atuais",
    "BIGQUERY_TABELA_ANTIGA": "momentos_antigos",
    "BIGQUERY_TABELA_DE_JOBS": "jobs",
    "BIGQUERY_TABELA_DE_REVISAO": "revisao",
    "BIGQUERY_TABELA_DE_EVENTOS": "eventos",
}


class FirestoreFalso:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.dados: dict[str, dict[str, dict[str, Any]]] = {}
        monkeypatch.setattr("api.nuvem.firestore.transactional", lambda f: f)

    def collection(self, nome: str) -> Any:
        dados = self.dados.setdefault(nome, {})
        colecao = Mock()

        def documento(id: str) -> Any:
            doc = Mock()
            doc.id = id
            doc.reference = doc
            doc.get.side_effect = lambda **_: Mock(
                exists=id in dados, to_dict=lambda: dados.get(id)
            )
            doc.to_dict.side_effect = lambda: dados.get(id)
            doc.delete.side_effect = lambda: dados.pop(id, None)

            def gravar(novos: dict[str, Any], merge: bool = False) -> None:
                destino = dados.setdefault(id, {}) if merge else {}
                for chave, valor in novos.items():
                    destino[chave] = (
                        destino.get(chave, 0) + valor.value
                        if isinstance(valor, firestore.Increment)
                        else valor
                    )
                dados[id] = destino

            doc.set.side_effect = gravar
            return doc

        colecao.document.side_effect = documento
        colecao.stream.side_effect = lambda: [documento(id) for id in list(dados)]
        colecao.where.side_effect = lambda *, filter: Mock(
            stream=lambda: [
                documento(id)
                for id, d in list(dados.items())
                if d.get(filter.field_path) == filter.value
            ]
        )
        return colecao

    def transaction(self) -> Any:
        return Mock(set=lambda doc, dados, **kw: doc.set(dados, **kw))


class BigQueryFalso:
    def __init__(self) -> None:
        self.banco = sqlite3.connect(":memory:", check_same_thread=False)
        self.banco.create_function("CONCAT", 2, lambda a, b: a + b)
        self.chamadas: list[dict[str, Any]] = []
        for tabela, campo in [
            ("momentos_atuais", "job_id"),
            ("momentos_antigos", "job_id"),
            ("jobs", "id"),
            ("revisao", "job_id"),
        ]:
            self.banco.execute(f"CREATE TABLE `projeto-teste.dados.{tabela}` ({campo})")
            self.banco.executemany(
                f"INSERT INTO `projeto-teste.dados.{tabela}` VALUES (?)",
                [("j1",), ("j2",)],
            )
        self.banco.execute(
            "CREATE TABLE `projeto-teste.dados.eventos` "
            "(id, tipo, quando, quem_tipo, quem_id, job_id)"
        )
        self.banco.commit()

    def __call__(self, corpo: dict[str, Any]) -> dict[str, Any]:
        self.chamadas.append(corpo)
        parametros = {
            p["name"]: p["parameterValue"]["value"] for p in corpo["queryParameters"]
        }
        antes = self.banco.total_changes
        try:
            for comando in (
                corpo["query"]
                .replace("CURRENT_TIMESTAMP()", "CURRENT_TIMESTAMP")
                .split(";")
            ):
                if comando.strip():
                    self.banco.execute(comando, parametros)
        except sqlite3.Error:
            # Como o BigQuery: erro no meio do script desfaz a transação inteira.
            self.banco.rollback()
            raise
        return {
            "jobComplete": True,
            "numDmlAffectedRows": str(self.banco.total_changes - antes),
        }


def test_apaga_dados_so_do_video_e_repetir_nao_subtrai_duas_vezes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.dados_da_purga import DadosDaPurga
    from api.nuvem import TiposDeObjetoFirestore

    banco = FirestoreFalso(monkeypatch)
    tipos = TiposDeObjetoFirestore(banco)  # type: ignore[arg-type]
    tipos.registrar("j1", {"sapato": 2, "saia": 1})
    tipos.registrar("j2", {"sapato": 3})
    banco.dados[COLECAO_DA_REVISAO] = {
        "j1:a": {"job_id": "j1"},
        "j1:b": {"job_id": "j1"},
        "j2:a": {"job_id": "j2"},
    }
    bq = BigQueryFalso()
    dados = DadosDaPurga(banco, AMBIENTE, bq)  # type: ignore[arg-type]
    dados.apagar("j1")
    dados.apagar("j1")

    assert banco.dados[COLECAO_DOS_TIPOS_DE_OBJETO]["sapato"]["total"] == 3
    assert banco.dados[COLECAO_DOS_TIPOS_DE_OBJETO]["saia"]["total"] == 0
    assert set(banco.dados[COLECAO_DOS_TIPOS_DE_OBJETO_POR_JOB]) == {"j2"}
    assert set(banco.dados[COLECAO_DA_REVISAO]) == {"j2:a"}
    for tabela in ("momentos_atuais", "momentos_antigos", "jobs", "revisao"):
        assert bq.banco.execute(
            f"SELECT * FROM `projeto-teste.dados.{tabela}`"
        ).fetchall() == [("j2",)]
    assert bq.banco.execute(
        "SELECT tipo, job_id FROM `projeto-teste.dados.eventos`"
    ).fetchall() == [("purga", "j1")]


@pytest.mark.parametrize(
    "resposta",
    [
        None,
        {"jobComplete": False},
        {"jobComplete": True, "errors": [{"reason": "invalidQuery"}]},
    ],
)
def test_falha_ou_falta_de_confirmacao_do_bigquery_mantem_job_para_repetir(
    monkeypatch: pytest.MonkeyPatch,
    resposta: dict[str, Any] | None,
) -> None:
    from api.dados_da_purga import DadosDaPurga

    banco = FirestoreFalso(monkeypatch)
    bq = BigQueryFalso()
    mundo = Mundo()
    transporte = Mock(
        side_effect=ConnectionError("fora") if resposta is None else None,
        return_value=resposta,
    )
    dados = DadosDaPurga(banco, AMBIENTE, transporte)  # type: ignore[arg-type]
    purga = mundo.purga(apagar_dados=dados.apagar)
    with pytest.raises((RuntimeError, ConnectionError)):
        purga.purgar("j1", None)
    assert (job := mundo.jobs.obter("j1")) is not None and job.lixeira is not None

    transporte.side_effect = bq
    purga.purgar("j1", None)
    assert mundo.jobs.obter("j1") is None


def test_purga_manual_usa_a_mesma_limpeza_dos_dados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.dados_da_purga import DadosDaPurga

    banco = FirestoreFalso(monkeypatch)
    bq = BigQueryFalso()
    dados = DadosDaPurga(banco, AMBIENTE, bq)  # type: ignore[arg-type]
    mundo = Mundo(apagar_dados=dados.apagar)
    assert mundo.purgar().status_code == 200
    assert mundo.jobs.obter("j1") is None
    assert bq.banco.execute("SELECT * FROM `projeto-teste.dados.jobs`").fetchall() == [
        ("j2",)
    ]


def test_sem_tabela_antiga_configurada_a_purga_continua(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.dados_da_purga import DadosDaPurga

    banco = FirestoreFalso(monkeypatch)
    bq = BigQueryFalso()
    bq.banco.execute("DROP TABLE `projeto-teste.dados.momentos_antigos`")
    ambiente = {k: v for k, v in AMBIENTE.items() if k != "BIGQUERY_TABELA_ANTIGA"}
    dados = DadosDaPurga(banco, ambiente, bq)  # type: ignore[arg-type]
    dados.apagar("j1")
    assert bq.banco.execute("SELECT * FROM `projeto-teste.dados.jobs`").fetchall() == [
        ("j2",)
    ]


def test_sem_a_tabela_antiga_a_purga_falha_antes_de_apagar_e_desfaz_o_bigquery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entre os dois applies da #567 a variável aponta para uma tabela que não existe."""
    from api.dados_da_purga import DadosDaPurga

    banco = FirestoreFalso(monkeypatch)
    banco.dados[COLECAO_DA_REVISAO] = {"j1:a": {"job_id": "j1"}}
    bq = BigQueryFalso()
    bq.banco.execute("DROP TABLE `projeto-teste.dados.momentos_antigos`")
    bq.banco.commit()
    mundo = Mundo()
    dados = DadosDaPurga(banco, AMBIENTE, bq)  # type: ignore[arg-type]
    purga = mundo.purga(apagar_dados=dados.apagar)
    with pytest.raises(sqlite3.OperationalError):
        purga.purgar("j1", None)
    assert (job := mundo.jobs.obter("j1")) is not None and job.lixeira is not None
    assert set(banco.dados[COLECAO_DA_REVISAO]) == {"j1:a"}
    for tabela in ("momentos_atuais", "jobs", "revisao"):
        assert bq.banco.execute(
            f"SELECT * FROM `projeto-teste.dados.{tabela}`"
        ).fetchall() == [("j1",), ("j2",)]
    assert (
        bq.banco.execute("SELECT * FROM `projeto-teste.dados.eventos`").fetchall() == []
    )


def test_limpeza_unica_resumida_e_idempotente_sem_tocar_nos_jobs_vivos(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from api.limpar_residuos_da_purga import VIDEO_PURGADO, limpar
    from api.nuvem import TiposDeObjetoFirestore

    banco = FirestoreFalso(monkeypatch)
    tipos = TiposDeObjetoFirestore(banco)  # type: ignore[arg-type]
    tipos.registrar(VIDEO_PURGADO, {"sapato": 2})
    tipos.registrar("j1", {"sapato": 3})
    banco.dados["decisoes_legadas"] = {str(n): {"decisao": "a"} for n in range(6)}
    bq = BigQueryFalso()
    bq.banco.executemany(
        "INSERT INTO `projeto-teste.dados.momentos_antigos` VALUES (?)",
        [(VIDEO_PURGADO,)] * 47,
    )
    bq.banco.commit()
    ambiente = AMBIENTE | {"FIRESTORE_COLECAO_DECISOES_DE_SUGESTAO": "decisoes_legadas"}
    limpar(banco, ambiente, bq)  # type: ignore[arg-type]
    assert (
        capsys.readouterr().out
        == "momentos antigos: 47; contribuição de tipos: 1; decisões de sugestão: 6\n"
    )
    limpar(banco, ambiente, bq)  # type: ignore[arg-type]
    assert (
        capsys.readouterr().out
        == "momentos antigos: 0; contribuição de tipos: 0; decisões de sugestão: 0\n"
    )
    assert banco.dados[COLECAO_DOS_TIPOS_DE_OBJETO]["sapato"]["total"] == 3
    assert set(banco.dados[COLECAO_DOS_TIPOS_DE_OBJETO_POR_JOB]) == {"j1"}
    assert banco.dados["decisoes_legadas"] == {}
    for tabela in ("momentos_atuais", "momentos_antigos", "jobs", "revisao"):
        assert bq.banco.execute(
            f"SELECT * FROM `projeto-teste.dados.{tabela}`"
        ).fetchall() == [("j1",), ("j2",)]


def test_limpeza_recusa_video_ainda_vivo_antes_de_apagar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.limpar_residuos_da_purga import VIDEO_PURGADO, limpar
    from api.nuvem import COLECAO_DE_JOBS

    banco = FirestoreFalso(monkeypatch)
    banco.dados[COLECAO_DE_JOBS] = {VIDEO_PURGADO: {"id": VIDEO_PURGADO}}
    bq = BigQueryFalso()
    ambiente = AMBIENTE | {"FIRESTORE_COLECAO_DECISOES_DE_SUGESTAO": "decisoes_legadas"}
    with pytest.raises(RuntimeError, match="ainda existe"):
        limpar(banco, ambiente, bq)  # type: ignore[arg-type]
    assert bq.chamadas == []
