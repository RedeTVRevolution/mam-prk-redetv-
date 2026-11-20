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
    "BIGQUERY_TABELA_DA_TAXA": "taxa",
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
            ("taxa", "job_id"),
            ("jobs", "id, programa, duracao_ms, quem_tipo, quem_id, estado, criado_em"),
            ("revisao", "job_id"),
        ]:
            self.banco.execute(f"CREATE TABLE `projeto-teste.dados.{tabela}` ({campo})")
            self.banco.executemany(
                f"INSERT INTO `projeto-teste.dados.{tabela}` ({campo.split(',')[0]})"
                " VALUES (?)",
                [("j1",), ("j2",)],
            )
        self.banco.execute("INSERT INTO `projeto-teste.dados.taxa` VALUES (NULL)")
        self.banco.execute(
            "CREATE TABLE `projeto-teste.dados.eventos` "
            "(id, tipo, quando, quem_tipo, quem_id, job_id, programa, estado, "
            "duracao_do_video_ms, criado_em)"
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
    for tabela in ("momentos_atuais", "jobs", "revisao"):
        assert bq.banco.execute(
            f"SELECT {'id' if tabela == 'jobs' else 'job_id'} "
            f"FROM `projeto-teste.dados.{tabela}`"
        ).fetchall() == [("j2",)]
    # A linha antiga, sem job_id, não se apaga por vídeo.
    assert bq.banco.execute(
        "SELECT * FROM `projeto-teste.dados.taxa` ORDER BY job_id"
    ).fetchall() == [(None,), ("j2",)]
    assert bq.banco.execute(
        "SELECT tipo, job_id FROM `projeto-teste.dados.eventos`"
    ).fetchall() == [("purga", "j1")]


def _marcador(bq: BigQueryFalso) -> tuple[Any, ...]:
    return bq.banco.execute(
        "SELECT quem_tipo, quem_id, programa, estado, duracao_do_video_ms, criado_em "
        "FROM `projeto-teste.dados.eventos` WHERE tipo = 'purga'"
    ).fetchone()


def test_o_marcador_leva_o_dono_e_os_dados_da_linha_do_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.dados_da_purga import DadosDaPurga

    bq = BigQueryFalso()
    bq.banco.execute(
        "UPDATE `projeto-teste.dados.jobs` SET programa = 'Jornal', duracao_ms = 5000, "
        "quem_tipo = 'usuario', quem_id = 'u1', estado = 'concluido', "
        "criado_em = '2026-11-01 10:00:00' WHERE id = 'j1'"
    )
    bq.banco.commit()
    DadosDaPurga(FirestoreFalso(monkeypatch), AMBIENTE, bq).apagar("j1")  # type: ignore[arg-type]
    assert _marcador(bq) == (
        "usuario",
        "u1",
        "Jornal",
        "concluido",
        5000,
        "2026-11-01 10:00:00",
    )
    assert bq.banco.execute("SELECT * FROM `projeto-teste.dados.jobs`").fetchall() == [
        ("j2", None, None, None, None, None, None)
    ]


@pytest.mark.parametrize(
    "linha",
    [
        "UPDATE `projeto-teste.dados.jobs` SET quem_tipo = 'usuario', programa = 'X' "
        "WHERE id = 'j1'",
        "UPDATE `projeto-teste.dados.jobs` SET quem_id = 'u1', programa = 'X' "
        "WHERE id = 'j1'",
        "DELETE FROM `projeto-teste.dados.jobs` WHERE id = 'j1'",
    ],
)
def test_sem_linha_ou_sem_dono_completo_o_marcador_e_do_sistema_purga_e_barra_de_novo(
    monkeypatch: pytest.MonkeyPatch, linha: str
) -> None:
    from api.dados_da_purga import DadosDaPurga

    bq = BigQueryFalso()
    bq.banco.execute(linha)
    bq.banco.commit()
    dados = DadosDaPurga(FirestoreFalso(monkeypatch), AMBIENTE, bq)  # type: ignore[arg-type]
    dados.apagar("j1")
    dados.apagar("j1")
    assert _marcador(bq) == ("sistema", "purga", None, None, None, None)
    assert bq.banco.execute(
        "SELECT COUNT(*) FROM `projeto-teste.dados.eventos` WHERE job_id = 'j1'"
    ).fetchone() == (1,)


def test_o_marcador_antigo_continua_barrando_a_reinsercao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.dados_da_purga import DadosDaPurga

    bq = BigQueryFalso()
    bq.banco.execute(
        "INSERT INTO `projeto-teste.dados.eventos` (id, tipo, quando, quem_tipo, "
        "quem_id, job_id) VALUES ('purga:j1', 'purga', 'x', 'sistema', 'purga', 'j1')"
    )
    bq.banco.commit()
    DadosDaPurga(FirestoreFalso(monkeypatch), AMBIENTE, bq).apagar("j1")  # type: ignore[arg-type]
    assert bq.banco.execute(
        "SELECT COUNT(*) FROM `projeto-teste.dados.eventos` WHERE job_id = 'j1'"
    ).fetchone() == (1,)


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
    assert bq.banco.execute("SELECT id FROM `projeto-teste.dados.jobs`").fetchall() == [
        ("j2",)
    ]


def test_sem_a_tabela_da_taxa_a_purga_falha_no_meio_e_desfaz_o_bigquery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A falha na tabela da taxa, já dentro da transação, desfaz os DELETEs e o marcador."""
    from api.dados_da_purga import DadosDaPurga

    banco = FirestoreFalso(monkeypatch)
    banco.dados[COLECAO_DA_REVISAO] = {"j1:a": {"job_id": "j1"}}
    bq = BigQueryFalso()
    bq.banco.execute("DROP TABLE `projeto-teste.dados.taxa`")
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
            f"SELECT {'id' if tabela == 'jobs' else 'job_id'} "
            f"FROM `projeto-teste.dados.{tabela}`"
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
    ambiente = AMBIENTE | {"FIRESTORE_COLECAO_DECISOES_DE_SUGESTAO": "decisoes_legadas"}
    limpar(banco, ambiente)  # type: ignore[arg-type]
    assert (
        capsys.readouterr().out == "contribuição de tipos: 1; decisões de sugestão: 6\n"
    )
    limpar(banco, ambiente)  # type: ignore[arg-type]
    assert (
        capsys.readouterr().out == "contribuição de tipos: 0; decisões de sugestão: 0\n"
    )
    assert banco.dados[COLECAO_DOS_TIPOS_DE_OBJETO]["sapato"]["total"] == 3
    assert set(banco.dados[COLECAO_DOS_TIPOS_DE_OBJETO_POR_JOB]) == {"j1"}
    assert banco.dados["decisoes_legadas"] == {}


def test_limpeza_recusa_video_ainda_vivo_antes_de_apagar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.limpar_residuos_da_purga import VIDEO_PURGADO, limpar
    from api.nuvem import COLECAO_DE_JOBS

    banco = FirestoreFalso(monkeypatch)
    banco.dados[COLECAO_DE_JOBS] = {VIDEO_PURGADO: {"id": VIDEO_PURGADO}}
    ambiente = AMBIENTE | {"FIRESTORE_COLECAO_DECISOES_DE_SUGESTAO": "decisoes_legadas"}
    with pytest.raises(RuntimeError, match="ainda existe"):
        limpar(banco, ambiente)  # type: ignore[arg-type]


def test_script_da_purga_nao_tem_select_com_where_e_sem_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # O BigQuery recusa "SELECT <literais> WHERE ..." (http 400), o SQLite aceita:
    # o BigQuery falso não pega, então o teste olha o texto de cada comando.
    from api.dados_da_purga import DadosDaPurga

    bq = BigQueryFalso()
    DadosDaPurga(FirestoreFalso(monkeypatch), AMBIENTE, bq).apagar("j1")  # type: ignore[arg-type]
    for comando in bq.chamadas[0]["query"].split(";"):
        antes_do_where = comando.split("WHERE", 1)[0]
        if "SELECT" in antes_do_where:
            assert "FROM" in antes_do_where.split("SELECT", 1)[1], comando
