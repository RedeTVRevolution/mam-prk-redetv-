from datetime import UTC, datetime
from typing import Annotated, cast

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from api.auditoria import (
    FiltroDeAuditoria,
    RegistroDeAuditoria,
    RepositorioDeAuditoriaEmMemoria,
)
from api.auth import Sistema, Usuario
from api.jobs import ServicoIndisponivel
from api.painel import AcessosAoPainel, exige_painel
from api.papeis import Papel
from api.tests.test_auth import VerificadorFalso

AGORA = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
ANA = Usuario(uid="ana", email="Ana@RedeTV.com.br")
CABECALHO = {"Authorization": "Bearer ana"}


def test_abrir_o_painel_grava_quem_quando_e_o_filtro() -> None:
    auditoria = RepositorioDeAuditoriaEmMemoria()
    AcessosAoPainel(auditoria, lambda: AGORA).abriu(ANA, {"de": "2026-10-01"})

    [r] = auditoria.consultar(FiltroDeAuditoria(acao="painel.aberto")).registros
    assert (r.uid, r.email, r.quando) == ("ana", "ana@redetv.com.br", AGORA)
    assert r.detalhes == {"filtro": {"de": "2026-10-01"}}


def test_exportar_em_csv_grava_a_acao_propria() -> None:
    auditoria = RepositorioDeAuditoriaEmMemoria()
    AcessosAoPainel(auditoria, lambda: AGORA).exportou(ANA, {"programa": "Hoje"})

    [r] = auditoria.consultar(FiltroDeAuditoria(acao="painel.exportado")).registros
    assert r.detalhes == {"filtro": {"programa": "Hoje"}}


class AuditoriaQueFalha(RepositorioDeAuditoriaEmMemoria):
    def acrescentar(self, registro: RegistroDeAuditoria) -> None:
        raise RuntimeError("Firestore fora")


def test_sem_registro_na_auditoria_o_acesso_nao_passa() -> None:
    acessos = AcessosAoPainel(AuditoriaQueFalha(), lambda: AGORA)

    with pytest.raises(ServicoIndisponivel):
        acessos.abriu(ANA, {})
    with pytest.raises(ServicoIndisponivel):
        acessos.exportou(ANA, {})


def test_chave_de_sistema_nao_ve_o_painel() -> None:
    sistema = Sistema(sistema="playout", escopos=["ler"])

    with pytest.raises(HTTPException) as erro:
        exige_painel(cast(Request, None), sistema)

    assert erro.value.status_code == 403


def _cliente(papeis: list[Papel]) -> TestClient:
    from api.main import criar_app
    from api.papeis import RepositorioDePapeisEmMemoria

    repo = RepositorioDePapeisEmMemoria()
    repo.salvar("ana", papeis)
    app: FastAPI = criar_app(verificador=VerificadorFalso({"ana": ANA}), papeis=repo)

    def _rota(_: Annotated[Usuario, Depends(exige_painel)]) -> dict[str, str]:
        return {"ok": "sim"}

    app.add_api_route("/v1/_painel_teste", _rota)
    # Antes da rota que devolve o front, que responde 404 a todo `/v1` desconhecido.
    app.router.routes.insert(0, app.router.routes.pop())

    return TestClient(app)


@pytest.mark.parametrize("papel", ["diretoria", "administrador"])
def test_dependencia_deixa_passar_quem_tem_painel_ver(papel: Papel) -> None:
    resposta = _cliente([papel]).get("/v1/_painel_teste", headers=CABECALHO)

    assert resposta.status_code == 200


@pytest.mark.parametrize("papel", ["consulta", "operador", "editor", "curador"])
def test_dependencia_barra_os_outros_papeis(papel: Papel) -> None:
    resposta = _cliente([papel]).get("/v1/_painel_teste", headers=CABECALHO)

    assert resposta.status_code == 403
    assert resposta.json()["detail"] == "Sem a permissão painel.ver"
