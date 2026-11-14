"""Período do envio (`enviado_de` e `enviado_ate`) no `GET /v1/jobs` (#623)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from api.jobs import FiltroDeJobs, Job, PaginaDeJobs, RepositorioEmMemoria
from api.nuvem import RepositorioFirestore, limites_do_envio
from api.tests.test_nuvem import EMULADOR_FIRESTORE
from api.tests.test_programas_no_acervo import PERIODO, Mundo, _programas

# 02:59 UTC é 23:59 do dia anterior em São Paulo (UTC-3); 03:00 UTC já é o dia seguinte.
MEIA_NOITE = datetime(2026, 10, 11, 3, 0, tzinfo=UTC)
ENVIO: dict[str, Any] = {
    "enviado_de": date(2026, 11, 1),
    "enviado_ate": date(2026, 11, 3),
}
ENVIO_NO_FIRESTORE = ["criado_em:GREATER_THAN_OR_EQUAL", "criado_em:LESS_THAN"]


def _job(id: str, quando: datetime, **extra: Any) -> Job:
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=1,
        estado="concluido",
        criado_por=extra.pop("criado_por", "u1"),
        criado_em=quando,
        atualizado_em=quando,
        **extra,
    )


def _cliente() -> firestore.Client:
    return firestore.Client(
        project="teste",
        credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
    )


def _consulta(
    monkeypatch: pytest.MonkeyPatch, filtro: FiltroDeJobs, por_mes: bool = True
) -> list[str]:
    repositorio = RepositorioFirestore(_cliente(), "jobs", listagem_por_mes=por_mes)
    vista: dict[str, Any] = {}

    def captura(consulta: Any, campo: str, f: FiltroDeJobs) -> PaginaDeJobs:
        vista["consulta"] = consulta
        return PaginaDeJobs([])

    monkeypatch.setattr(repositorio, "_ordenar_e_ler", captura)
    repositorio.consultar(filtro)
    return [
        f"{f.field.field_path}:{f.op.name}"
        for f in getattr(vista["consulta"], "_field_filters", ())
    ]


def _ids(repositorio: Any, **filtro: Any) -> list[str]:
    return [j.id for j in repositorio.consultar(FiltroDeJobs(**filtro)).jobs]


class TestFiltroEmPython:
    def test_dia_do_envio_segue_sao_paulo_nas_duas_pontas(self) -> None:
        repositorio = RepositorioEmMemoria()
        antes = MEIA_NOITE - timedelta(minutes=1)  # 10/10 23:59 em São Paulo
        for id, quando in (("antes", antes), ("depois", MEIA_NOITE)):
            repositorio.salvar(_job(id, quando))

        dia_10, dia_11 = date(2026, 10, 10), date(2026, 10, 11)
        assert _ids(repositorio, enviado_de=dia_11) == ["depois"]
        assert _ids(repositorio, enviado_ate=dia_10) == ["antes"]
        assert _ids(repositorio, enviado_de=dia_10, enviado_ate=dia_10) == ["antes"]
        assert _ids(repositorio, enviado_de=dia_10, enviado_ate=dia_11) == [
            "depois",
            "antes",
        ]


class TestRota:
    def test_periodo_do_envio_filtra_e_as_pontas_sao_inclusivas(self) -> None:
        mundo = Mundo()
        mundo.jobs.salvar(_job("a", MEIA_NOITE - timedelta(minutes=1)))
        mundo.jobs.salvar(_job("b", MEIA_NOITE))

        assert mundo.ids("enviado_de=2026-10-11&enviado_ate=2026-10-11") == ["b"]
        assert mundo.ids("enviado_de=2026-10-10&enviado_ate=2026-10-10") == ["a"]
        assert mundo.ids("enviado_ate=2026-10-10") == ["a"]

    def test_sem_periodo_responde_como_hoje(self) -> None:
        assert len(Mundo().ids()) == 4

    @pytest.mark.parametrize(
        "consulta",
        [
            "enviado_de=ontem",
            "enviado_ate=2026-13-01",
            "enviado_de=2026-11-05&enviado_ate=2026-11-04",
        ],
    )
    def test_data_invalida_ou_invertida_da_422(self, consulta: str) -> None:
        assert Mundo().get(consulta).status_code == 422

    def test_mesmo_dia_nas_duas_pontas_vale(self) -> None:
        resposta = Mundo().get("enviado_de=2026-11-05&enviado_ate=2026-11-05")

        assert resposta.status_code == 200

    def test_lista_sem_capa_nao_mistura_periodos_no_cache(self) -> None:
        mundo = Mundo()
        mundo.jobs.salvar(_job("velho", datetime(2026, 10, 1, 12, tzinfo=UTC)))

        antigo = mundo.ids("capa=false&enviado_de=2026-10-01&enviado_ate=2026-10-01")
        recente = mundo.ids("capa=false&enviado_de=2026-11-01")

        assert antigo == ["velho"]
        assert "velho" not in recente

    def test_chave_de_sistema_continua_vendo_so_os_proprios_jobs(self) -> None:
        mundo = Mundo()
        mundo.jobs.salvar(
            _job("meu", MEIA_NOITE, sistema="s1", criado_por="sistema:s1")
        )
        mundo.jobs.salvar(_job("alheio", MEIA_NOITE))

        assert mundo.ids("enviado_de=2026-10-11", mundo.chave("s1")) == ["meu"]


class TestConsultaNoFirestore:
    def test_ordem_enviado_manda_as_duas_pontas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _consulta(monkeypatch, FiltroDeJobs(**ENVIO)) == ENVIO_NO_FIRESTORE

    def test_cada_ponta_vai_sozinha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        de = FiltroDeJobs(enviado_de=date(2026, 11, 1))
        ate = FiltroDeJobs(enviado_ate=date(2026, 11, 1))

        assert _consulta(monkeypatch, de) == ["criado_em:GREATER_THAN_OR_EQUAL"]
        assert _consulta(monkeypatch, ate) == ["criado_em:LESS_THAN"]

    def test_limites_sao_a_meia_noite_de_sao_paulo(self) -> None:
        de, ate = limites_do_envio(FiltroDeJobs(**ENVIO))

        assert de == datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
        assert ate == datetime(2026, 11, 4, 3, 0, tzinfo=UTC)  # exclusivo: dia 4, 00h

    def test_ordem_exibicao_deixa_o_periodo_do_envio_para_o_python(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _consulta(monkeypatch, FiltroDeJobs(ordem="exibicao", **ENVIO)) == []

    def test_ordem_exibicao_com_data_de_exibicao_nao_manda_o_envio(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        filtro = FiltroDeJobs(ordem="exibicao", **PERIODO, **ENVIO)

        assert _consulta(monkeypatch, filtro) == [
            "data_exibicao:GREATER_THAN_OR_EQUAL",
            "data_exibicao:LESS_THAN_OR_EQUAL",
        ]


class TestTetos:
    def test_com_o_mes_dentro_conta_as_pontas_e_mantem_tudo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 3 meses × 5 programas = 15 disjunções; 15 × (programa, mês + 2 pontas + 2) = 90.
        filtro = FiltroDeJobs(programas=_programas(5), **PERIODO, **ENVIO)

        assert _consulta(monkeypatch, filtro) == [
            "programa:IN",
            *ENVIO_NO_FIRESTORE,
            "mes_exibicao:IN",
        ]

    def test_as_pontas_empurram_o_mes_para_fora_e_os_programas_ficam(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 3 meses × 7 programas = 21 disjunções × (programa, mês + 2 + 2) = 126 > 100.
        # Sem o mês, 7 × (programa + 2 + 2) = 35: os programas ficam, o envio também.
        filtro = FiltroDeJobs(programas=_programas(7), **PERIODO, **ENVIO)

        assert _consulta(monkeypatch, filtro) == ["programa:IN", *ENVIO_NO_FIRESTORE]

    def test_com_o_mes_fora_pelas_disjuncoes_programas_e_envio_ficam(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 3 meses × 11 programas = 33 > 30; sem o mês, 11 × (1 + 2 + 2) = 55.
        filtro = FiltroDeJobs(programas=_programas(11), **PERIODO, **ENVIO)

        assert _consulta(monkeypatch, filtro) == ["programa:IN", *ENVIO_NO_FIRESTORE]

    def test_sem_mes_e_com_programas_demais_so_o_envio_fica_na_consulta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 12 programas × 2 estados = 24 disjunções × (programa, estado + 2 + 2) = 144 > 100
        # (sem as pontas seria 96): os programas vão para Python, o envio continua.
        filtro = FiltroDeJobs(
            programas=_programas(12),
            estados=frozenset({"concluido", "falhou"}),
            **ENVIO,
        )

        assert _consulta(monkeypatch, filtro) == ["estado:IN", *ENVIO_NO_FIRESTORE]

    def test_sem_o_envio_os_mesmos_programas_cabem(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        filtro = FiltroDeJobs(
            programas=_programas(12), estados=frozenset({"concluido", "falhou"})
        )

        assert _consulta(monkeypatch, filtro) == ["programa:IN", "estado:IN"]


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestNoEmulador:
    @staticmethod
    def _repositorio() -> RepositorioFirestore:
        return RepositorioFirestore(_cliente(), f"jobs-{uuid.uuid4().hex}")

    def test_ordem_enviado_traz_so_o_periodo_na_meia_noite_de_sao_paulo(self) -> None:
        repositorio = self._repositorio()
        for id, quando in (
            ("a", MEIA_NOITE - timedelta(minutes=1)),
            ("b", MEIA_NOITE),
            ("c", MEIA_NOITE + timedelta(days=1, hours=20)),
            ("d", MEIA_NOITE + timedelta(days=2)),
        ):
            repositorio.salvar(_job(id, quando))

        assert _ids(
            repositorio, enviado_de=date(2026, 10, 11), enviado_ate=date(2026, 10, 12)
        ) == ["c", "b"]
        assert _ids(repositorio, enviado_ate=date(2026, 10, 10)) == ["a"]

    def test_ordem_exibicao_confere_o_envio_em_python_sem_filtro_de_exibicao(
        self,
    ) -> None:
        repositorio = self._repositorio()
        for i in range(1, 6):
            repositorio.salvar(
                _job(
                    f"j{i}",
                    datetime(2026, 11, i, 15, tzinfo=UTC),
                    data_exibicao=date(2026, 10, 10 + i),
                )
            )

        pagina = _ids(
            repositorio,
            ordem="exibicao",
            enviado_de=date(2026, 11, 2),
            enviado_ate=date(2026, 11, 4),
            limite=2,
        )

        assert pagina == ["j4", "j3"]
