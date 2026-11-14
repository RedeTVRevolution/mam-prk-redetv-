"""Filtro de programa do Acervo com várias escolhas: `GET /v1/jobs?programa=a&programa=b` (#622)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from api.auth import Escopo, Usuario
from api.cache_curto import CacheCurto
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.jobs import FiltroDeJobs, Job, PaginaDeJobs, RepositorioEmMemoria
from api.main import criar_app
from api.nuvem import (
    MAXIMO_DE_COMPONENTES,
    MAXIMO_DE_DISJUNCOES,
    RepositorioFirestore,
)
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso
from api.tests.test_nuvem import EMULADOR_FIRESTORE

AGORA = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
MAC = MacSimulado({1: b"k1"}, versao_atual=1)
PESSOA = {"Authorization": "Bearer token-bom"}


def _job(id: str, minutos: int = 0, sistema: str | None = None, **extra: Any) -> Job:
    quando = AGORA + timedelta(minutes=minutos)
    return Job(
        id=id,
        nome=f"{id}.mp4",
        tamanho_bytes=10,
        estado=extra.pop("estado", "concluido"),
        criado_por="u1" if sistema is None else f"sistema:{sistema}",
        sistema=sistema,
        criado_em=quando,
        atualizado_em=quando,
        **extra,
    )


class Mundo:
    def __init__(self) -> None:
        self.segundos = 0.0
        self.jobs = RepositorioEmMemoria()
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("u1", ["editor"])
        self.chaves = RepositorioDeChavesEmMemoria()
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
                self.jobs,
                ArmazenamentoFalso(),
                chaves=VerificadorDeChaveDeApi(self.chaves, MAC),
                papeis=papeis,
                cache_da_lista=CacheCurto(15.0, relogio=lambda: self.segundos),
            )
        )
        for i, programa in enumerate(["Bola na Rede", "Vizinhos", "Jornal", None]):
            self.jobs.salvar(_job(f"j{i}", i, programa=programa))

    def chave(self, sistema: str) -> dict[str, str]:
        escopos = cast(frozenset[Escopo], frozenset({"ler"}))
        return {
            "X-API-Key": emitir_chave(sistema, escopos, MAC, self.chaves, AGORA).chave
        }

    def get(self, consulta: str = "", cabecalhos: dict[str, str] = PESSOA) -> Any:
        return self.cliente.get(f"/v1/jobs?{consulta}", headers=cabecalhos)

    def ids(self, consulta: str = "", cabecalhos: dict[str, str] = PESSOA) -> list[str]:
        resposta = self.get(consulta, cabecalhos)
        assert resposta.status_code == 200, resposta.text
        return [j["id"] for j in resposta.json()]


def test_programa_repetido_traz_so_os_marcados() -> None:
    mundo = Mundo()

    assert mundo.ids("programa=Bola+na+Rede&programa=Vizinhos") == ["j1", "j0"]
    assert mundo.ids("programa=Jornal") == ["j2"]


def test_sem_programa_responde_como_hoje() -> None:
    assert Mundo().ids() == ["j3", "j2", "j1", "j0"]


def test_valor_vazio_e_ignorado_e_so_vazios_valem_todos() -> None:
    mundo = Mundo()

    assert mundo.ids("programa=&programa=Jornal&programa=") == ["j2"]
    assert mundo.ids("programa=&programa=") == ["j3", "j2", "j1", "j0"]


def test_programa_repetido_conta_uma_vez() -> None:
    assert Mundo().ids("programa=Jornal&programa=Jornal") == ["j2"]


def test_valor_com_mais_de_100_caracteres_da_422() -> None:
    mundo = Mundo()

    assert mundo.ids("programa=" + "a" * 100) == []
    assert mundo.get("programa=" + "a" * 101).status_code == 422


def test_valor_com_caractere_de_controle_da_422() -> None:
    assert Mundo().get("programa=a%00b").status_code == 422


def test_mais_de_200_valores_da_422_e_200_passa() -> None:
    mundo = Mundo()

    assert mundo.ids("&".join(f"programa=p{i}" for i in range(200))) == []
    assert mundo.get("&".join(f"programa=p{i}" for i in range(201))).status_code == 422


def test_o_teto_de_200_conta_os_distintos_e_repetidos_valem_uma_vez() -> None:
    mundo = Mundo()

    assert mundo.get("&".join(["programa=Jornal"] * 201)).status_code == 200
    assert mundo.get("&".join(f"programa=p{i}" for i in range(201))).status_code == 422


def test_o_teto_vale_tambem_para_chave_que_pede_outro_sistema() -> None:
    mundo = Mundo()
    programas = "&".join(f"programa=p{i}" for i in range(201))

    assert (
        mundo.get(f"sistema=outro&{programas}", mundo.chave("rtv")).status_code == 422
    )


def test_chave_de_sistema_so_ve_os_proprios_jobs() -> None:
    mundo = Mundo()
    mundo.jobs.salvar(_job("meu", 9, sistema="rtv", programa="Jornal"))

    assert mundo.ids("programa=Jornal&programa=Vizinhos", mundo.chave("rtv")) == ["meu"]


def test_lista_sem_capa_respeita_os_programas_e_o_cache_usa_o_filtro_inteiro() -> None:
    mundo = Mundo()

    a = "capa=false&programa=Jornal&programa=Vizinhos"
    assert mundo.ids(a) == ["j2", "j1"]
    mundo.jobs.salvar(_job("novo", 10, programa="Jornal"))
    # Mesmo filtro, na validade: a lista guardada; a ordem dos valores não muda a chave.
    assert mundo.ids("capa=false&programa=Vizinhos&programa=Jornal") == ["j2", "j1"]
    # Outro conjunto de programas não reaproveita a lista guardada.
    assert mundo.ids("capa=false&programa=Jornal") == ["novo", "j2"]
    mundo.segundos = 16
    assert mundo.ids(a) == ["novo", "j2", "j1"]


def test_filtro_de_jobs_com_programas_e_hasheavel() -> None:
    filtro = FiltroDeJobs(programas=frozenset({"a", "b"}))

    assert hash(filtro) == hash(FiltroDeJobs(programas=frozenset({"b", "a"})))
    assert filtro != FiltroDeJobs(programas=frozenset({"a"}))


def test_paginas_com_varios_programas_nao_pulam_nem_repetem() -> None:
    mundo = Mundo()
    for i in range(10):
        mundo.jobs.salvar(_job(f"x{i:02d}", 20 + i, programa=["A", "B", "C"][i % 3]))

    vistos: list[str] = []
    cursor = ""
    while True:
        resposta = mundo.get(f"programa=A&programa=B&limite=3{cursor}")
        vistos += [j["id"] for j in resposta.json()]
        proximo = resposta.headers.get("X-Proximo-Cursor")
        if not proximo:
            break
        cursor = f"&cursor={proximo}"

    assert vistos == [f"x{i:02d}" for i in reversed(range(10)) if i % 3 != 2]


# --- Firestore: o que vai à consulta e o que fica em Python -----------------------------


def _cliente() -> firestore.Client:
    return firestore.Client(
        project="teste",
        credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
    )


def _consulta(
    monkeypatch: pytest.MonkeyPatch, filtro: FiltroDeJobs, por_mes: bool = True
) -> list[str]:
    """Os filtros que o repositório manda ao Firestore, como `campo:operador`."""
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


def _programas(n: int) -> frozenset[str]:
    return frozenset(f"p{i:02d}" for i in range(n))


PERIODO: dict[str, Any] = {
    "exibicao_de": date(2026, 8, 20),
    "exibicao_ate": date(2026, 10, 3),
}  # 3 meses


class TestConsultaNoFirestore:
    def test_um_programa_usa_igualdade(self, monkeypatch: pytest.MonkeyPatch) -> None:
        filtro = FiltroDeJobs(programas=frozenset({"a"}))

        assert _consulta(monkeypatch, filtro) == ["programa:EQUAL"]

    def test_varios_programas_usam_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _consulta(monkeypatch, FiltroDeJobs(programas=_programas(5))) == [
            "programa:IN"
        ]

    def test_sem_programas_nao_manda_programa(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _consulta(monkeypatch, FiltroDeJobs()) == []

    def test_programa_in_com_mes_cabe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 3 meses × 5 programas = 15 disjunções; 15 × (programa, mês + ordem + id) = 60.
        filtro = FiltroDeJobs(programas=_programas(5), **PERIODO)

        assert _consulta(monkeypatch, filtro) == ["programa:IN", "mes_exibicao:IN"]

    def test_estourou_o_teto_de_disjuncoes_o_mes_sai_primeiro(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 3 meses × 11 programas = 33 disjunções (> 30): sem o mês, 11 cabem.
        filtro = FiltroDeJobs(programas=_programas(11), **PERIODO)

        assert _consulta(monkeypatch, filtro) == ["programa:IN"]

    def test_estourou_o_teto_de_componentes_o_mes_sai_primeiro(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 2 meses × 2 estados × 7 programas = 28 disjunções × (programa, estado, mês + 2)
        # = 140 componentes (> 100); sem o mês, 14 × 4 = 56.
        filtro = FiltroDeJobs(
            programas=_programas(7),
            estados=frozenset({"concluido", "falhou"}),
            exibicao_de=date(2026, 9, 1),
            exibicao_ate=date(2026, 10, 3),
        )

        assert _consulta(monkeypatch, filtro) == ["programa:IN", "estado:IN"]

    def test_15_programas_e_2_estados_saem_da_consulta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 30 disjunções (cabe), mas 30 × (programa, estado + 2) = 120 > 100: o programa sai.
        filtro = FiltroDeJobs(
            programas=_programas(15), estados=frozenset({"concluido", "falhou"})
        )

        assert _consulta(monkeypatch, filtro) == ["estado:IN"]

    def test_valem_sem_periodo_e_na_ordem_por_exibicao(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 31 programas passam das 30 disjunções: saem; 30 cabem (30 × 3 = 90).
        fora = FiltroDeJobs(programas=_programas(31), ordem="exibicao", **PERIODO)
        assert _consulta(monkeypatch, fora) == [
            "data_exibicao:GREATER_THAN_OR_EQUAL",
            "data_exibicao:LESS_THAN_OR_EQUAL",
        ]
        dentro = FiltroDeJobs(programas=_programas(30), ordem="exibicao")
        assert _consulta(monkeypatch, dentro) == ["programa:IN"]

    def test_na_ordem_por_exibicao_as_datas_contam_nos_componentes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 30 programas × (programa + 2 datas + 2) = 150 > 100: o programa sai.
        filtro = FiltroDeJobs(programas=_programas(30), ordem="exibicao", **PERIODO)

        assert _consulta(monkeypatch, filtro) == [
            "data_exibicao:GREATER_THAN_OR_EQUAL",
            "data_exibicao:LESS_THAN_OR_EQUAL",
        ]

    def test_os_tetos_do_firestore_nao_mudaram(self) -> None:
        assert (MAXIMO_DE_DISJUNCOES, MAXIMO_DE_COMPONENTES) == (30, 100)


@pytest.mark.skipif(not EMULADOR_FIRESTORE, reason="sem emulador do Firestore")
class TestNoEmulador:
    @staticmethod
    def _repositorio() -> RepositorioFirestore:
        return RepositorioFirestore(
            _cliente(), f"jobs-{uuid.uuid4().hex}", listagem_por_mes=True
        )

    @staticmethod
    def _todas_as_paginas(
        repositorio: RepositorioFirestore, filtro: FiltroDeJobs
    ) -> list[str]:
        vistos: list[str] = []
        cursor = None
        for _ in range(100):
            pagina = repositorio.consultar(
                FiltroDeJobs(**{**filtro.__dict__, "limite": 4, "cursor": cursor})
            )
            vistos += [j.id for j in pagina.jobs]
            cursor = pagina.proximo_cursor
            if cursor is None:
                return vistos
        raise AssertionError("não terminou")

    def test_varios_programas_dentro_da_consulta_paginam_sem_pular_nem_repetir(
        self,
    ) -> None:
        repositorio = self._repositorio()
        for i in range(14):
            repositorio.salvar(_job(f"j{i:02d}", i, programa=["A", "B", "C"][i % 3]))

        vistos = self._todas_as_paginas(
            repositorio, FiltroDeJobs(programas=frozenset({"A", "B"}))
        )

        assert vistos == [f"j{i:02d}" for i in reversed(range(14)) if i % 3 != 2]

    def test_programas_conferidos_em_python_paginam_sem_pular_nem_repetir(
        self,
    ) -> None:
        repositorio = self._repositorio()
        for i in range(20):
            repositorio.salvar(
                _job(
                    f"j{i:02d}",
                    i,
                    programa=f"p{i % 15:02d}",
                    estado="concluido" if i % 2 else "falhou",
                )
            )
        # 14 programas × 2 estados: 28 disjunções, 28 × 4 = 112 componentes > 100, então o
        # programa sai da consulta e é conferido em Python.
        filtro = FiltroDeJobs(
            programas=_programas(14), estados=frozenset({"concluido", "falhou"})
        )

        vistos = self._todas_as_paginas(repositorio, filtro)

        assert vistos == [f"j{i:02d}" for i in reversed(range(20)) if i % 15 != 14]

    def test_com_o_mes_fora_o_resultado_e_o_esperado(self) -> None:
        repositorio = self._repositorio()
        for i in range(12):
            repositorio.salvar(
                _job(
                    f"j{i:02d}",
                    i,
                    programa=f"p{i:02d}",
                    data_exibicao=[
                        date(2026, 8, 25),
                        date(2026, 9, 5),
                        date(2026, 10, 1),
                    ][i % 3],
                )
            )
        filtro = FiltroDeJobs(programas=_programas(11), **PERIODO)  # mês sai (33 > 30)

        vistos = [j.id for j in repositorio.consultar(filtro).jobs]

        assert vistos == [f"j{i:02d}" for i in reversed(range(11))]
