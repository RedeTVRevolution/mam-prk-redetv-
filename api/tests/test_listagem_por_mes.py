"""Filtro do período por `mes_exibicao` na lista por envio (#479)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from api.gravar_mes_nos_jobs import gravar
from api.jobs import FiltroDeJobs, Job, PaginaDeJobs
from api.nuvem import (
    RepositorioFirestore,
    listagem_por_mes_do_ambiente,
    meses_do_periodo,
    plano_da_consulta,
)
from api.tests.test_nuvem import EMULADOR_FIRESTORE

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def _job(id: str, minutos: int, **extra: Any) -> Job:
    quando = BASE + timedelta(minutes=minutos)
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=1,
        estado="concluido",
        criado_por="uid-1",
        criado_em=quando,
        atualizado_em=quando,
        **extra,
    )


def _cliente() -> firestore.Client:
    return firestore.Client(
        project="teste",
        credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
    )


def _filtro(**extra: Any) -> FiltroDeJobs:
    return FiltroDeJobs(
        exibicao_de=date(2026, 8, 20), exibicao_ate=date(2026, 10, 3), **extra
    )


def test_job_deriva_o_mes_da_data_de_exibicao() -> None:
    assert _job("a", 0, data_exibicao=date(2026, 10, 3)).mes_exibicao == "2026-10"
    assert _job("b", 0, data_exibicao="2026-02-28").mes_exibicao == "2026-02"
    assert _job("c", 0).mes_exibicao is None
    # Gravado com o mês errado (ou sem ele), o Job relido corrige.
    lido = Job(
        **{
            **_job("d", 0).model_dump(),
            "data_exibicao": "2026-05-01",
            "mes_exibicao": "x",
        }
    )
    assert lido.mes_exibicao == "2026-05"
    assert (
        _job("a", 0, data_exibicao=date(2026, 10, 3)).model_dump()["mes_exibicao"]
        == "2026-10"
    )


def test_meses_do_periodo_atravessa_a_virada_do_ano() -> None:
    assert meses_do_periodo(date(2025, 11, 30), date(2026, 2, 1)) == [
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
    ]
    assert meses_do_periodo(date(2026, 10, 1), date(2026, 10, 31)) == ["2026-10"]


class TestLimitesDoFirestore:
    def test_periodo_simples_usa_os_meses(self) -> None:
        assert plano_da_consulta(_filtro(), True)[0] == [
            "2026-08",
            "2026-09",
            "2026-10",
        ]

    def test_sem_uma_ponta_do_periodo_nao_usa(self) -> None:
        assert (
            plano_da_consulta(FiltroDeJobs(exibicao_de=date(2026, 8, 1)), True)[0]
            is None
        )
        assert plano_da_consulta(FiltroDeJobs(), True)[0] is None

    def test_mais_de_30_disjuncoes_nao_usa(self) -> None:
        # 31 meses, sem estado: 31 disjunções.
        filtro = FiltroDeJobs(
            exibicao_de=date(2024, 1, 1), exibicao_ate=date(2026, 7, 31)
        )
        assert len(meses_do_periodo(date(2024, 1, 1), date(2026, 7, 31))) == 31
        assert plano_da_consulta(filtro, True)[0] is None

    def test_5_meses_x_6_estados_com_programa_sistema_e_palavra_passa_dos_100_componentes(
        self,
    ) -> None:
        filtro = FiltroDeJobs(
            exibicao_de=date(2026, 6, 1),
            exibicao_ate=date(2026, 10, 1),
            estados=frozenset(
                {"concluido", "falhou", "cancelado", "processando", "enviado", "fila"}  # type: ignore[arg-type]
            ),
            programas=frozenset({"TV Fama"}),
            sistema="mam",
            palavras=("fama",),
        )
        assert len(filtro.estados) == 6
        assert plano_da_consulta(filtro, True)[0] is None

    def test_cabe_no_limite_de_componentes(self) -> None:
        # 3 meses × 2 estados × (programa, estado, mês + ordem + id) = 6 × 5 = 30.
        filtro = _filtro(
            estados=frozenset({"concluido", "falhou"}), programas=frozenset({"TV Fama"})
        )
        assert plano_da_consulta(filtro, True)[0] == ["2026-08", "2026-09", "2026-10"]


@pytest.mark.parametrize(
    ("ambiente", "ligada"),
    [
        ({}, False),
        ({"LISTAGEM_POR_MES": ""}, False),
        ({"LISTAGEM_POR_MES": "false"}, False),
        ({"LISTAGEM_POR_MES": " True "}, True),
    ],
)
def test_variavel_do_ambiente(ambiente: dict[str, str], ligada: bool) -> None:
    assert listagem_por_mes_do_ambiente(ambiente) is ligada


def test_variavel_com_valor_errado_levanta() -> None:
    with pytest.raises(ValueError, match="LISTAGEM_POR_MES"):
        listagem_por_mes_do_ambiente({"LISTAGEM_POR_MES": "ture"})


class TestConsulta:
    @staticmethod
    def _campos_da_consulta(
        monkeypatch: pytest.MonkeyPatch, listagem_por_mes: bool, filtro: FiltroDeJobs
    ) -> tuple[list[str], list[str]]:
        repositorio = RepositorioFirestore(
            _cliente(), colecao="jobs", listagem_por_mes=listagem_por_mes
        )
        vista: dict[str, Any] = {}

        def captura(consulta: Any, campo: str, f: FiltroDeJobs) -> PaginaDeJobs:
            vista["consulta"], vista["campo"] = consulta, campo
            return PaginaDeJobs([])

        monkeypatch.setattr(repositorio, "_ordenar_e_ler", captura)
        repositorio.consultar(filtro)
        # Sem filtro, a consulta ainda é a própria coleção.
        filtros = [
            f"{f.field.field_path}:{f.op.name}"
            for f in getattr(vista["consulta"], "_field_filters", ())
        ]
        return filtros, [vista["campo"]]

    def test_ligada_filtra_por_mes_e_ordena_por_envio(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        filtros, ordem = self._campos_da_consulta(monkeypatch, True, _filtro())
        assert filtros == ["mes_exibicao:IN"]
        assert ordem == ["criado_em"]

    def test_ligada_com_os_outros_filtros(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        filtros, ordem = self._campos_da_consulta(
            monkeypatch, True, _filtro(programas=frozenset({"TV Fama"}))
        )
        assert filtros == ["programa:EQUAL", "mes_exibicao:IN"]
        assert ordem == ["criado_em"]

    def test_desligada_nao_manda_a_data_ao_firestore(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        filtros, ordem = self._campos_da_consulta(monkeypatch, False, _filtro())
        assert filtros == []
        assert ordem == ["criado_em"]

    def test_limite_estourado_cai_no_caminho_de_hoje(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        filtro = FiltroDeJobs(
            exibicao_de=date(2024, 1, 1), exibicao_ate=date(2026, 7, 31)
        )
        filtros, ordem = self._campos_da_consulta(monkeypatch, True, filtro)
        assert filtros == []
        assert ordem == ["criado_em"]

    def test_na_ordem_por_exibicao_segue_o_intervalo_de_datas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        filtros, ordem = self._campos_da_consulta(
            monkeypatch, True, _filtro(ordem="exibicao")
        )
        assert filtros == [
            "data_exibicao:GREATER_THAN_OR_EQUAL",
            "data_exibicao:LESS_THAN_OR_EQUAL",
        ]
        assert ordem == ["data_exibicao"]


class _Doc:
    def __init__(self, dados: dict[str, Any]) -> None:
        self.dados, self.reference = dados, dados["id"]

    def to_dict(self) -> dict[str, Any]:
        return self.dados


class _Lote:
    def __init__(self, gravados: dict[str, Any], lotes: list[int]) -> None:
        self.gravados, self.lotes, self.n = gravados, lotes, 0

    def update(self, referencia: str, campos: dict[str, Any]) -> None:
        self.gravados[referencia] = campos
        self.n += 1

    def commit(self) -> None:
        self.lotes.append(self.n)


class _Colecao:
    def __init__(self, docs: list[_Doc]) -> None:
        self.docs = docs

    def stream(self) -> list[_Doc]:
        return self.docs


class _Cliente:
    def __init__(self) -> None:
        self.gravados: dict[str, Any] = {}
        self.lotes: list[int] = []

    def batch(self) -> _Lote:
        return _Lote(self.gravados, self.lotes)


class TestCarga:
    def _docs(self) -> list[_Doc]:
        antigo = _job("antigo", 0, data_exibicao=date(2026, 10, 3)).model_dump()
        antigo.pop("mes_exibicao")
        errado = {**antigo, "id": "errado", "mes_exibicao": "2026-01"}
        certo = _job("certo", 1, data_exibicao=date(2026, 9, 3)).model_dump()
        sem_data = _job("sem-data", 2).model_dump()
        return [_Doc(d) for d in (antigo, errado, certo, sem_data)]

    def test_grava_so_onde_falta_ou_esta_errado(self) -> None:
        cliente = _Cliente()

        contagem = gravar(_Colecao(self._docs()), cliente)

        assert contagem == {"gravados": 2, "iguais": 1, "sem_data": 1}
        assert cliente.gravados == {
            "antigo": {"mes_exibicao": "2026-10"},
            "errado": {"mes_exibicao": "2026-10"},
        }

    def test_repetir_nao_grava_de_novo(self) -> None:
        docs = self._docs()
        cliente = _Cliente()
        gravar(_Colecao(docs), cliente)
        for doc in docs:
            if doc.dados["id"] in cliente.gravados:
                doc.dados.update(cliente.gravados[doc.dados["id"]])

        segunda = gravar(_Colecao(docs), _Cliente())

        assert segunda == {"gravados": 0, "iguais": 3, "sem_data": 1}

    def test_grava_em_lotes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("api.gravar_mes_nos_jobs.LOTE", 2)
        cliente = _Cliente()
        docs = []
        for i in range(5):
            d = _job(f"j{i}", i, data_exibicao=date(2026, 10, 3)).model_dump()
            d.pop("mes_exibicao")
            docs.append(_Doc(d))

        assert gravar(_Colecao(docs), cliente)["gravados"] == 5
        assert cliente.lotes == [2, 2, 1]


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
def test_resultado_e_ordem_iguais_com_a_variavel_ligada_ou_desligada() -> None:
    cliente = _cliente()
    colecao = f"jobs-{uuid.uuid4().hex}"
    desligada = RepositorioFirestore(cliente, colecao=colecao)
    ligada = RepositorioFirestore(cliente, colecao=colecao, listagem_por_mes=True)
    datas = [
        date(2026, 8, 25),
        date(2026, 9, 1),
        date(2026, 10, 3),
        date(2026, 10, 4),
        None,
        date(2026, 7, 31),
    ]
    for i, d in enumerate(datas):
        desligada.salvar(_job(f"j{i}", i, data_exibicao=d))

    for limite in (None, 2):
        filtro = _filtro(limite=limite)
        esperado = desligada.consultar(filtro)
        achado = ligada.consultar(filtro)
        assert (
            [j.id for j in achado.jobs]
            == [j.id for j in esperado.jobs]
            == (["j2", "j1", "j0"] if limite is None else ["j2", "j1"])
        )
        assert achado.proximo_cursor == esperado.proximo_cursor
