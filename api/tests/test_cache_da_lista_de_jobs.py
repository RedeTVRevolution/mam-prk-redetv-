"""Cache de 15 s da lista de Jobs sem capa, a do polling da busca (#558)."""

from datetime import UTC, datetime
from typing import cast

from fastapi.testclient import TestClient

from api.auth import Escopo, Usuario
from api.cache_curto import CacheCurto
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.jobs import Job, RepositorioEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

AGORA = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
MAC = MacSimulado({1: b"k1"}, versao_atual=1)
PESSOA = {"Authorization": "Bearer token-bom"}


class Mundo:
    def __init__(self) -> None:
        self.segundos = 0.0
        self.jobs = RepositorioEmMemoria()
        self.papeis = RepositorioDePapeisEmMemoria()
        self.papeis.salvar("u1", ["editor"])
        self.chaves = RepositorioDeChavesEmMemoria()
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
                self.jobs,
                ArmazenamentoFalso(),
                chaves=VerificadorDeChaveDeApi(self.chaves, MAC),
                papeis=self.papeis,
                cache_da_lista=CacheCurto(15.0, relogio=lambda: self.segundos),
            )
        )

    def chave(self, sistema: str) -> dict[str, str]:
        escopos = cast(frozenset[Escopo], frozenset({"ler"}))
        return {
            "X-API-Key": emitir_chave(sistema, escopos, MAC, self.chaves, AGORA).chave
        }

    def job(self, id: str, sistema: str | None = None) -> None:
        self.jobs.salvar(
            Job(
                id=id,
                nome=f"{id}.mp4",
                tamanho_bytes=10,
                estado="concluido",
                criado_por="u1" if sistema is None else f"sistema:{sistema}",
                sistema=sistema,
                criado_em=AGORA,
                atualizado_em=AGORA,
            )
        )

    def ids(self, consulta: str = "", **cabecalhos: dict[str, str]) -> list[str]:
        resposta = self.cliente.get(
            f"/v1/jobs?capa=false{consulta}", headers=cabecalhos.get("h", PESSOA)
        )
        assert resposta.status_code == 200
        return [j["id"] for j in resposta.json()]


def test_a_lista_sem_capa_dura_15_s_e_depois_le_de_novo() -> None:
    mundo = Mundo()
    mundo.job("a")
    assert mundo.ids() == ["a"]

    mundo.job("b")
    mundo.segundos = 14.9
    assert mundo.ids() == ["a"]

    mundo.segundos = 15.0
    assert sorted(mundo.ids()) == ["a", "b"]


def test_a_lista_com_capa_nunca_fica_guardada() -> None:
    mundo = Mundo()
    mundo.job("a")
    mundo.cliente.get("/v1/jobs", headers=PESSOA)

    mundo.job("b")

    corpo = mundo.cliente.get("/v1/jobs", headers=PESSOA).json()
    assert sorted(j["id"] for j in corpo) == ["a", "b"]


def test_cada_filtro_e_cada_cursor_tem_a_sua_resposta() -> None:
    mundo = Mundo()
    for id in ("a", "b", "c"):
        mundo.job(id)

    primeira = mundo.cliente.get("/v1/jobs?capa=false&limite=2", headers=PESSOA)
    cursor = primeira.headers["x-proximo-cursor"]
    segunda = mundo.cliente.get(
        f"/v1/jobs?capa=false&limite=2&cursor={cursor}", headers=PESSOA
    )
    de_novo = mundo.cliente.get("/v1/jobs?capa=false&limite=2", headers=PESSOA)

    assert len(primeira.json()) == 2 and len(segunda.json()) == 1
    assert de_novo.json() == primeira.json()
    # O próximo cursor também vem do cache.
    assert de_novo.headers["x-proximo-cursor"] == cursor
    assert mundo.ids("&estado=falhou") == []


def test_o_cache_nao_mistura_sistemas() -> None:
    mundo = Mundo()
    mundo.job("do-a", "sis-a")
    mundo.job("do-b", "sis-b")

    todos = mundo.ids()
    do_a = mundo.ids(h=mundo.chave("sis-a"))
    do_b = mundo.ids(h=mundo.chave("sis-b"))
    pedindo_o_do_b = mundo.ids("&sistema=sis-b", h=mundo.chave("sis-a"))

    assert sorted(todos) == ["do-a", "do-b"]
    assert do_a == ["do-a"] and do_b == ["do-b"]
    assert pedindo_o_do_b == []  # uma chave não acha Job de outro sistema


def test_permissao_revogada_continua_recusada_com_o_cache_quente() -> None:
    mundo = Mundo()
    mundo.job("a")
    assert mundo.ids() == ["a"]

    mundo.papeis.salvar("u1", [])

    resposta = mundo.cliente.get("/v1/jobs?capa=false", headers=PESSOA)
    assert resposta.status_code == 403
