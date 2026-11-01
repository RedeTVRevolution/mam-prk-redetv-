from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from api.auditoria import (
    FiltroDeAuditoria,
    RegistroDeAuditoria,
    RepositorioDeAuditoriaEmMemoria,
)
from api.auth import Usuario
from api.main import criar_app
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
AUTORIZACAO = {"Authorization": "Bearer token-bom"}


def _registro(id: str, minutos: int = 0, **extra: object) -> RegistroDeAuditoria:
    campos: dict[str, object] = {
        "id": id,
        "quando": BASE + timedelta(minutes=minutos),
        "uid": "u1",
        "email": "ana@redetv.com",
        "acao": "chave.emitida",
        "alvo_tipo": "sistema",
        "alvo_id": "s1",
        "alvo_nome": "Playout",
    }
    campos.update(extra)
    return RegistroDeAuditoria(**campos)  # type: ignore[arg-type]


def _ids(repo: RepositorioDeAuditoriaEmMemoria, **filtro: object) -> list[str]:
    pagina = repo.consultar(FiltroDeAuditoria(**filtro))  # type: ignore[arg-type]
    return [r.id for r in pagina.registros]


def test_acrescenta_e_lista_do_mais_recente_para_o_mais_antigo() -> None:
    repo = RepositorioDeAuditoriaEmMemoria()
    repo.acrescentar(_registro("a", 0))
    repo.acrescentar(_registro("c", 20))
    repo.acrescentar(_registro("b", 10))

    assert _ids(repo) == ["c", "b", "a"]


def test_a_interface_so_acrescenta_e_consulta() -> None:
    publicos = {
        n for n in dir(RepositorioDeAuditoriaEmMemoria) if not n.startswith("_")
    }

    assert publicos == {"acrescentar", "consultar"}


def test_filtra_por_uid_e_por_email_da_pessoa() -> None:
    repo = RepositorioDeAuditoriaEmMemoria()
    repo.acrescentar(_registro("a", uid="u1", email="ana@redetv.com"))
    repo.acrescentar(_registro("b", uid="u2", email="rui@redetv.com"))

    assert _ids(repo, pessoa="u2") == ["b"]
    assert _ids(repo, pessoa="Ana@RedeTV.com") == ["a"]


def test_filtra_por_alvo_e_por_acao() -> None:
    repo = RepositorioDeAuditoriaEmMemoria()
    repo.acrescentar(_registro("a", alvo_id="v1", acao="item.para_lixeira"))
    repo.acrescentar(_registro("b", alvo_id="v2", acao="item.para_lixeira"))
    repo.acrescentar(_registro("c", alvo_id="v1", acao="item.restaurado"))

    assert _ids(repo, alvo_id="v1") == ["c", "a"]
    assert _ids(repo, acao="item.para_lixeira") == ["b", "a"]
    assert _ids(repo, alvo_id="v1", acao="item.para_lixeira") == ["a"]


def test_filtra_por_periodo_com_limites_incluidos() -> None:
    repo = RepositorioDeAuditoriaEmMemoria()
    for i, minutos in enumerate((0, 10, 20, 30)):
        repo.acrescentar(_registro(str(i), minutos))

    de, ate = BASE + timedelta(minutes=10), BASE + timedelta(minutes=20)
    assert _ids(repo, de=de, ate=ate) == ["2", "1"]


def test_pagina_por_cursor_sem_repetir_nem_perder() -> None:
    repo = RepositorioDeAuditoriaEmMemoria()
    for i in range(5):
        repo.acrescentar(_registro(f"r{i}", i))

    p1 = repo.consultar(FiltroDeAuditoria(limite=2))
    p2 = repo.consultar(FiltroDeAuditoria(limite=2, cursor=p1.proximo_cursor))
    p3 = repo.consultar(FiltroDeAuditoria(limite=2, cursor=p2.proximo_cursor))

    assert [r.id for r in p1.registros] == ["r4", "r3"]
    assert [r.id for r in p2.registros] == ["r2", "r1"]
    assert [r.id for r in p3.registros] == ["r0"]
    assert p3.proximo_cursor is None


def _cliente(papeis: list[Papel], repo: RepositorioDeAuditoriaEmMemoria) -> TestClient:
    repo_papeis = RepositorioDePapeisEmMemoria()
    repo_papeis.salvar("u1", papeis)
    return TestClient(
        criar_app(
            VerificadorFalso({"token-bom": Usuario(uid="u1", email="a@b.c")}),
            papeis=repo_papeis,
            auditoria=repo,
        )
    )


def test_sem_auditoria_ver_a_rota_responde_403() -> None:
    repo = RepositorioDeAuditoriaEmMemoria()
    repo.acrescentar(_registro("a"))

    for papel in ("consulta", "operador", "editor", "curador"):
        resposta = _cliente([papel], repo).get(
            "/v1/admin/auditoria", headers=AUTORIZACAO
        )
        assert resposta.status_code == 403


def test_o_administrador_lista_filtrado_e_pagina() -> None:
    repo = RepositorioDeAuditoriaEmMemoria()
    repo.acrescentar(_registro("a", 0, alvo_id="v1"))
    repo.acrescentar(_registro("b", 1, alvo_id="v2"))
    repo.acrescentar(_registro("c", 2, alvo_id="v1"))
    cliente = _cliente(["administrador"], repo)

    filtrada = cliente.get("/v1/admin/auditoria?alvo=v1&limite=1", headers=AUTORIZACAO)

    assert filtrada.status_code == 200
    assert [r["id"] for r in filtrada.json()] == ["c"]
    assert filtrada.json()[0]["alvo_nome"] == "Playout"
    cursor = filtrada.headers["X-Proximo-Cursor"]
    segunda = cliente.get(
        f"/v1/admin/auditoria?alvo=v1&limite=1&cursor={cursor}", headers=AUTORIZACAO
    )
    assert [r["id"] for r in segunda.json()] == ["a"]
    assert "X-Proximo-Cursor" not in segunda.headers


def test_filtros_de_acao_e_periodo_na_rota() -> None:
    repo = RepositorioDeAuditoriaEmMemoria()
    repo.acrescentar(_registro("a", 0, acao="conta.criada"))
    repo.acrescentar(_registro("b", 60, acao="conta.criada"))
    repo.acrescentar(_registro("c", 60, acao="conta.desativada"))
    cliente = _cliente(["administrador"], repo)

    resposta = cliente.get(
        "/v1/admin/auditoria",
        params={
            "acao": "conta.criada",
            "de": (BASE + timedelta(minutes=30)).isoformat(),
        },
        headers=AUTORIZACAO,
    )

    assert [r["id"] for r in resposta.json()] == ["b"]


def test_acao_fora_da_lista_e_cursor_inexistente_dao_422() -> None:
    cliente = _cliente(["administrador"], RepositorioDeAuditoriaEmMemoria())

    assert (
        cliente.get(
            "/v1/admin/auditoria?acao=qualquer", headers=AUTORIZACAO
        ).status_code
        == 422
    )
    assert (
        cliente.get("/v1/admin/auditoria?cursor=nada", headers=AUTORIZACAO).status_code
        == 422
    )
