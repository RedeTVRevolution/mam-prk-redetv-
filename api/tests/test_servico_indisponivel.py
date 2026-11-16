"""Serviço fora do ar responde 503, na rota, na autenticação e na busca (#663)."""

import logging
from collections.abc import Iterable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import PermissionDenied, ServiceUnavailable

from api.auth import Usuario
from api.chaves import (
    MacSimulado,
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.jobs import RepositorioEmMemoria
from api.mac_kms import ErroDoKms
from api.main import CABECALHOS_DE_SEGURANCA, criar_app
from api.modelo_do_job import Job
from api.papeis import DocumentoDePapeis, RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_busca import AUTORIZACAO, cliente, job, objeto, pedido
from api.tests.test_chave_de_api import BASE, TODOS
from api.tests.test_jobs import ArmazenamentoFalso

CORPO = {"detail": "Serviço indisponível"}
BEARER = {"Authorization": "Bearer token-bom"}


def _fora() -> ServiceUnavailable:
    return ServiceUnavailable("Firestore fora")  # type: ignore[no-untyped-call]


class JobsQueCaem(RepositorioEmMemoria):
    fora = False

    def obter(self, job_id: str) -> Job | None:
        if self.fora:
            raise _fora()
        return super().obter(job_id)

    def obter_varios(
        self, job_ids: Iterable[str], so_a_lista: bool = False
    ) -> list[Job]:
        if self.fora:
            raise _fora()
        return super().obter_varios(job_ids, so_a_lista)

    def consultar(self, filtro: Any) -> Any:
        if self.fora:
            raise _fora()
        return super().consultar(filtro)

    def listar(self) -> list[Job]:
        if self.fora:
            raise _fora()
        return super().listar()


class PapeisQueCaem(RepositorioDePapeisEmMemoria):
    def ler(self, uid: str) -> DocumentoDePapeis:
        raise _fora()


def _app(jobs: Any = None, **kw: Any) -> TestClient:
    papeis = kw.pop("papeis", None)
    if papeis is None:
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("u1", ["editor"])
    return TestClient(
        criar_app(
            VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
            jobs or RepositorioEmMemoria(),
            ArmazenamentoFalso(),
            papeis=papeis,
            **kw,
        ),
        raise_server_exceptions=False,
    )


@pytest.mark.parametrize(
    "caminho", ["/v1/jobs", "/v1/jobs/j1", "/v1/jobs/j1/reproducao"]
)
def test_rotas_de_jobs_com_firestore_fora_respondem_503(
    caminho: str, caplog: pytest.LogCaptureFixture
) -> None:
    jobs = JobsQueCaem()
    jobs.fora = True

    with caplog.at_level(logging.WARNING):
        r = _app(jobs).get(caminho, headers=BEARER)

    assert (r.status_code, r.json()) == (503, CORPO)
    assert "Firestore fora" in caplog.text


def test_pagina_2_da_busca_com_firestore_fora_responde_503() -> None:
    c, m = cliente(["consulta"], pedido(texto_livre="vestido"))
    m.com(job("j2"), objeto("o2", "j2", 0, 1_000))
    r1 = c.get("/v1/busca", params={"q": "vestido", "limite": 1}, headers=AUTORIZACAO)
    cursor = r1.headers["X-Proximo-Cursor"]

    def fora(_ids: Any) -> Any:
        raise _fora()

    # A página 2 relê os Jobs da lista guardada, fora do `lido(...)` da 1ª página.
    m.jobs.obter_varios = fora  # type: ignore[assignment]
    r = TestClient(c.app, raise_server_exceptions=False).get(
        "/v1/busca",
        params={"q": "vestido", "limite": 1, "cursor": cursor},
        headers=AUTORIZACAO,
    )

    assert (r.status_code, r.json()) == (503, CORPO)


class MacQueCai(MacSimulado):
    def verificar(self, versao: int, mensagem: bytes, mac: bytes) -> bool:
        raise ErroDoKms("KMS fora")


def test_chave_com_kms_fora_responde_503_com_cabecalhos_de_seguranca(
    caplog: pytest.LogCaptureFixture,
) -> None:
    chaves = RepositorioDeChavesEmMemoria()
    chave = emitir_chave(
        "Legado", TODOS, MacSimulado({1: b"k1"}, 1), chaves, BASE
    ).chave
    c = _app(chaves=VerificadorDeChaveDeApi(chaves, MacQueCai({1: b"k1"}, 1)))

    with caplog.at_level(logging.WARNING):
        r = c.get("/v1/jobs", headers={"X-API-Key": chave})

    assert (r.status_code, r.json()) == (503, CORPO)
    for nome, valor in CABECALHOS_DE_SEGURANCA.items():
        assert r.headers[nome] == valor
    assert "KMS fora" in caplog.text


def test_papeis_com_firestore_fora_respondem_503_com_cabecalhos_de_seguranca() -> None:
    r = _app(papeis=PapeisQueCaem()).get("/v1/jobs", headers=BEARER)

    assert (r.status_code, r.json()) == (503, CORPO)
    for nome, valor in CABECALHOS_DE_SEGURANCA.items():
        assert r.headers[nome] == valor


def test_google_api_error_de_configuracao_tambem_e_503_com_a_causa_no_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Nega(RepositorioDePapeisEmMemoria):
        def ler(self, uid: str) -> DocumentoDePapeis:
            raise PermissionDenied("sem permissão no índice")  # type: ignore[no-untyped-call]

    with caplog.at_level(logging.WARNING):
        r = _app(papeis=Nega()).get("/v1/jobs", headers=BEARER)

    assert r.status_code == 503
    assert "sem permissão no índice" in caplog.text


def test_erro_comum_continua_500() -> None:
    class Quebra(RepositorioDePapeisEmMemoria):
        def ler(self, uid: str) -> DocumentoDePapeis:
            raise RuntimeError("bug")

    assert _app(papeis=Quebra()).get("/v1/jobs", headers=BEARER).status_code == 500


def test_falha_ao_gravar_a_troca_de_versao_do_mac_nao_derruba_a_chave() -> None:
    antigo = MacSimulado({1: b"k1"}, 1)
    novo = MacSimulado({1: b"k1", 2: b"k2"}, 2)
    chaves = RepositorioDeChavesEmMemoria()
    chave = emitir_chave("Legado", TODOS, antigo, chaves, BASE).chave

    def salvar_fora(_registro: Any) -> None:
        raise _fora()

    chaves.salvar = salvar_fora  # type: ignore[assignment]
    r = _app(chaves=VerificadorDeChaveDeApi(chaves, novo)).get(
        "/v1/jobs", headers={"X-API-Key": chave}
    )

    assert r.status_code == 200


def test_falha_do_jwks_do_google_continua_500() -> None:
    import jwt

    from api.auth import VerificadorIdentityPlatform

    def sem_rede(_token: str) -> Any:
        raise jwt.PyJWKClientConnectionError("google fora")

    app = criar_app(VerificadorIdentityPlatform("p", chave_publica=sem_rede))
    r = TestClient(app, raise_server_exceptions=False).get("/v1/eu", headers=BEARER)

    assert r.status_code == 500
