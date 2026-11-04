"""As rotas `/v1/painel/...` (#282): quem vê, os filtros, os números dos acessos e o CSV."""

import csv
import io
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.chaves import (
    RepositorioDeChavesEmMemoria,
    VerificadorDeChaveDeApi,
    emitir_chave,
)
from api.copia_bigquery import _parametro
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.resumos_de_uso import (
    AcessoDoDia,
    ConfigDosResumos,
    ResumosBigQuery,
    ResumosEmMemoria,
)
from api.tests.test_auth import VerificadorFalso
from api.tests.test_escopos import MAC
from api.usuarios import ContaDoIdentityPlatform, ContasDeUsuarioEmMemoria

ANA = Usuario(uid="ana", email="ana@redetv.com.br")
CABECALHO = {"Authorization": "Bearer ana"}


def _acesso(dia: int, uid: str, acessos: int, ativo: bool = True) -> AcessoDoDia:
    return AcessoDoDia(
        dia=date(2026, 11, dia),
        uid=uid,
        acessos=acessos,
        ativo=ativo,
        ultimo_acesso=datetime(2026, 11, dia, 15, 0, tzinfo=UTC),
    )


LINHAS = [
    _acesso(1, "bia", 2),
    _acesso(1, "caio", 1),
    _acesso(2, "bia", 1),
    # Só o fim do processamento do vídeo dele: sem login nem ação, não é ativo.
    _acesso(2, "caio", 0, ativo=False),
    _acesso(3, "bia", 3),
]


class Mundo:
    def __init__(self, papeis: list[str], resumos: Any = "padrao") -> None:
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        repo = RepositorioDePapeisEmMemoria()
        repo.salvar("ana", papeis)  # type: ignore[arg-type]
        self.resumos = (
            ResumosEmMemoria(LINHAS, ["Hoje", "Fofocalizando"])
            if resumos == "padrao"
            else resumos
        )
        self.cliente = TestClient(
            criar_app(
                verificador=VerificadorFalso({"ana": ANA}),
                papeis=repo,
                auditoria=self.auditoria,
                resumos_de_uso=self.resumos,
                contas=ContasDeUsuarioEmMemoria(
                    [
                        ContaDoIdentityPlatform(uid="bia", email="bia@redetv.com.br"),
                        ContaDoIdentityPlatform(uid="caio", email="caio@redetv.com.br"),
                    ]
                ),
            )
        )

    def get(self, rota: str, **params: str) -> Any:
        return self.cliente.get(f"/v1/painel{rota}", params=params, headers=CABECALHO)


def _diretoria() -> Mundo:
    return Mundo(["diretoria"])


@pytest.mark.parametrize("rota", ["/acessos", "/filtros"])
@pytest.mark.parametrize("papel", ["consulta", "operador", "editor", "curador"])
def test_sem_painel_ver_e_403(rota: str, papel: str) -> None:
    mundo = Mundo([papel])

    assert mundo.get(rota).status_code == 403
    assert mundo.auditoria.consultar(FiltroDeAuditoria()).registros == []


def test_chave_de_sistema_e_403() -> None:
    chaves = RepositorioDeChavesEmMemoria()
    emitida = emitir_chave(
        "Playout", frozenset({"ler"}), MAC, chaves, datetime(2026, 11, 4, tzinfo=UTC)
    )
    app = criar_app(
        verificador=VerificadorFalso({}),
        chaves=VerificadorDeChaveDeApi(chaves, MAC),
        resumos_de_uso=ResumosEmMemoria(),
    )

    resposta = TestClient(app).get(
        "/v1/painel/acessos", headers={"X-API-Key": emitida.chave}
    )

    assert resposta.status_code == 403


def test_sem_bigquery_e_503() -> None:
    assert Mundo(["diretoria"], resumos=None).get("/acessos").status_code == 503


def test_acessos_por_dia_por_usuario_e_no_total() -> None:
    resposta = _diretoria().get("/acessos")

    assert resposta.status_code == 200
    r = resposta.json()
    assert r["total"] == {"acessos": 7, "usuarios_ativos": 2}
    assert r["por_dia"] == [
        {"dia": "2026-11-01", "acessos": 3, "usuarios_ativos": 2},
        {"dia": "2026-11-02", "acessos": 1, "usuarios_ativos": 1},
        {"dia": "2026-11-03", "acessos": 3, "usuarios_ativos": 1},
    ]
    assert [
        (u["uid"], u["email"], u["acessos"], u["dias_ativos"]) for u in r["por_usuario"]
    ] == [
        ("bia", "bia@redetv.com.br", 6, 3),
        ("caio", "caio@redetv.com.br", 1, 1),
    ]
    assert r["por_usuario"][0]["ultimo_acesso"] == "2026-11-03T15:00:00Z"


def test_filtra_pelo_periodo_e_pelo_usuario() -> None:
    mundo = _diretoria()

    r = mundo.get("/acessos", desde="2026-11-02", ate="2026-11-02").json()
    assert (r["total"]["acessos"], len(r["por_dia"])) == (1, 1)
    r = mundo.get("/acessos", usuario="caio").json()
    assert [u["uid"] for u in r["por_usuario"]] == ["caio"]
    assert r["total"]["acessos"] == 1


def test_periodo_invertido_e_422() -> None:
    resposta = _diretoria().get("/acessos", desde="2026-11-03", ate="2026-11-01")

    assert resposta.status_code == 422


def test_acessos_com_programa_e_422_e_vazio_vale_todos() -> None:
    mundo = _diretoria()

    assert mundo.get("/acessos", programa="Hoje").status_code == 422
    assert mundo.get("/acessos", programa="").status_code == 200


def test_filtros_oferecem_programas_e_usuarios_ativos() -> None:
    r = _diretoria().get("/filtros").json()

    assert r["programas"] == ["Fofocalizando", "Hoje"]
    assert r["usuarios"] == [
        {"uid": "bia", "email": "bia@redetv.com.br"},
        {"uid": "caio", "email": "caio@redetv.com.br"},
    ]


def test_csv_tem_uma_linha_por_dia_e_pessoa() -> None:
    resposta = _diretoria().get("/acessos", formato="csv", usuario="bia")

    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/csv")
    assert "acessos.csv" in resposta.headers["content-disposition"]
    linhas = list(csv.reader(io.StringIO(resposta.text)))
    assert linhas[0] == ["dia", "uid", "email", "acessos", "ativo", "ultimo_acesso"]
    assert linhas[1] == [
        "2026-11-01",
        "bia",
        "bia@redetv.com.br",
        "2",
        "sim",
        "2026-11-01T15:00:00+00:00",
    ]
    assert len(linhas) == 4


def test_abrir_e_baixar_gravam_a_auditoria_com_o_filtro() -> None:
    mundo = _diretoria()

    mundo.get("/acessos", desde="2026-11-01")
    mundo.get("/acessos", desde="2026-11-01")  # recarga: não grava de novo
    mundo.get("/acessos", desde="2026-11-01", formato="csv")
    mundo.get("/filtros")  # só os nomes dos filtros: sem registro

    abertos = mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.aberto")
    ).registros
    exportados = mundo.auditoria.consultar(
        FiltroDeAuditoria(acao="painel.exportado")
    ).registros
    assert [r.detalhes for r in abertos] == [
        {"aba": "acessos", "filtro": {"desde": "2026-11-01"}}
    ]
    assert [r.uid for r in exportados] == ["ana"]


def test_consulta_do_bigquery_filtra_com_parametros_e_converte_as_linhas() -> None:
    pedidos: list[dict[str, Any]] = []

    def transporte(corpo: dict[str, Any]) -> dict[str, Any]:
        pedidos.append(corpo)
        return {
            "jobComplete": True,
            "rows": [
                {
                    "f": [
                        {"v": "2026-11-01"},
                        {"v": "bia"},
                        {"v": "2"},
                        {"v": "true"},
                        {"v": "2026-11-01T15:00:00Z"},
                    ]
                },
                {
                    "f": [
                        {"v": "2026-11-02"},
                        {"v": "bia"},
                        {"v": "0"},
                        {"v": "false"},
                        {"v": None},
                    ]
                },
            ],
        }

    resumos = ResumosBigQuery(
        ConfigDosResumos("proj", "ds", "regiao", "por_usuario", "por_programa"),
        transporte,
    )

    linhas = resumos.acessos(date(2026, 11, 1), None, "bia'; DROP TABLE x")

    assert linhas == [
        AcessoDoDia(
            date(2026, 11, 1), "bia", 2, True, datetime(2026, 11, 1, 15, tzinfo=UTC)
        ),
        AcessoDoDia(date(2026, 11, 2), "bia", 0, False, None),
    ]
    [pedido] = pedidos
    assert "`proj.ds.por_usuario`" in pedido["query"]
    assert "DROP" not in pedido["query"]
    assert pedido["queryParameters"] == [
        _parametro("desde", "2026-11-01", "DATE"),
        _parametro("usuario", "bia'; DROP TABLE x"),
    ]


def test_consulta_que_nao_termina_ou_nao_cabe_falha_alto() -> None:
    resumos = ResumosBigQuery(
        ConfigDosResumos("p", "d", "r", "a", "b"),
        lambda corpo: {"jobComplete": False},
    )

    with pytest.raises(RuntimeError):
        resumos.acessos(None, None, None)
