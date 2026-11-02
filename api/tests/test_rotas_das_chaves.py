from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.chaves import MacSimulado, RepositorioDeChavesEmMemoria
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

AGORA = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
ADMIN = {"Authorization": "Bearer admin"}
ROTA = "/v1/admin/chaves"
PEDIDO = {"sistema": "Sistema Legado", "escopos": ["ler", "criar"]}


class Mundo:
    def __init__(self) -> None:
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("adm", ["administrador"])
        papeis.salvar("ed", ["editor"])
        self.repositorio = RepositorioDeChavesEmMemoria()
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "admin": Usuario(uid="adm", email="adm@redetv.com"),
                        "editor": Usuario(uid="ed", email="ed@redetv.com"),
                    }
                ),
                RepositorioEmMemoria(),
                ArmazenamentoFalso(),
                papeis=papeis,
                auditoria=self.auditoria,
                repositorio_de_chaves=self.repositorio,
                mac=MacSimulado({1: b"k1"}, versao_atual=1),
                relogio=lambda: AGORA,
            )
        )

    def emitir(self, pedido: dict[str, Any] = PEDIDO) -> dict[str, Any]:
        resposta = self.cliente.post(ROTA, json=pedido, headers=ADMIN)
        assert resposta.status_code == 201, resposta.text
        return dict(resposta.json())

    def registros(self) -> list[Any]:
        return self.auditoria.consultar(FiltroDeAuditoria()).registros


def test_emite_a_chave_uma_unica_vez_e_ela_funciona() -> None:
    mundo = Mundo()

    emitida = mundo.emitir()

    assert emitida["chave"].split(".")[1] == emitida["id"]
    assert emitida["sistema"] == "Sistema Legado"
    assert emitida["escopos"] == ["criar", "ler"]
    assert emitida["revogada_em"] is None
    outra = mundo.cliente.get("/v1/jobs", headers={"X-API-Key": emitida["chave"]})
    assert outra.status_code == 200


def test_lista_sem_a_chave_nem_o_hmac() -> None:
    mundo = Mundo()
    emitida = mundo.emitir()

    resposta = mundo.cliente.get(ROTA, headers=ADMIN)

    assert resposta.status_code == 200
    assert resposta.json() == [
        {
            "id": emitida["id"],
            "sistema": "Sistema Legado",
            "escopos": ["criar", "ler"],
            "criada_em": "2026-11-02T12:00:00Z",
            "revogada_em": None,
        }
    ]
    registro = mundo.repositorio.obter(emitida["id"])
    assert registro is not None
    assert emitida["chave"] not in resposta.text
    assert registro.hmac not in resposta.text


def test_revogar_faz_a_chave_receber_401_na_requisicao_seguinte() -> None:
    mundo = Mundo()
    emitida = mundo.emitir()
    chave = {"X-API-Key": emitida["chave"]}
    assert mundo.cliente.get("/v1/jobs", headers=chave).status_code == 200

    resposta = mundo.cliente.post(f"{ROTA}/{emitida['id']}/revogar", headers=ADMIN)

    assert resposta.status_code == 200
    assert resposta.json()["revogada_em"] == "2026-11-02T12:00:00Z"
    assert mundo.cliente.get("/v1/jobs", headers=chave).status_code == 401
    listada = mundo.cliente.get(ROTA, headers=ADMIN).json()[0]
    assert listada["revogada_em"] == "2026-11-02T12:00:00Z"


def test_revogar_de_novo_nao_repete_o_registro() -> None:
    mundo = Mundo()
    emitida = mundo.emitir()
    url = f"{ROTA}/{emitida['id']}/revogar"
    mundo.cliente.post(url, headers=ADMIN)

    resposta = mundo.cliente.post(url, headers=ADMIN)

    assert resposta.status_code == 200
    assert [r.acao for r in mundo.registros()].count("chave.revogada") == 1


def test_revogar_chave_inexistente_da_404() -> None:
    resposta = Mundo().cliente.post(f"{ROTA}/nao-existe/revogar", headers=ADMIN)

    assert resposta.status_code == 404


def test_sem_chaves_gerir_da_403_em_todas_as_rotas() -> None:
    mundo = Mundo()
    emitida = mundo.emitir()
    editor = {"Authorization": "Bearer editor"}

    respostas = [
        mundo.cliente.get(ROTA, headers=editor),
        mundo.cliente.post(ROTA, json=PEDIDO, headers=editor),
        mundo.cliente.post(f"{ROTA}/{emitida['id']}/revogar", headers=editor),
    ]

    assert [r.status_code for r in respostas] == [403, 403, 403]
    assert mundo.repositorio.obter(emitida["id"]).revogada_em is None  # type: ignore[union-attr]


def test_chave_de_sistema_nao_gere_chaves() -> None:
    mundo = Mundo()
    emitida = mundo.emitir()

    resposta = mundo.cliente.get(ROTA, headers={"X-API-Key": emitida["chave"]})

    assert resposta.status_code == 403


def test_sem_credencial_da_401() -> None:
    assert Mundo().cliente.get(ROTA).status_code == 401


def test_emitir_pede_sistema_e_ao_menos_um_escopo() -> None:
    mundo = Mundo()

    respostas = [
        mundo.cliente.post(ROTA, json={"sistema": "X", "escopos": []}, headers=ADMIN),
        mundo.cliente.post(
            ROTA, json={"sistema": "X", "escopos": ["apagar"]}, headers=ADMIN
        ),
        mundo.cliente.post(ROTA, json={"escopos": ["ler"]}, headers=ADMIN),
        mundo.cliente.post(
            ROTA, json={"sistema": "***", "escopos": ["ler"]}, headers=ADMIN
        ),
    ]

    assert [r.status_code for r in respostas] == [422, 422, 422, 422]
    assert mundo.repositorio.listar() == []


def test_terceira_chave_ativa_do_sistema_da_409() -> None:
    mundo = Mundo()
    mundo.emitir()
    mundo.emitir()

    resposta = mundo.cliente.post(ROTA, json=PEDIDO, headers=ADMIN)

    assert resposta.status_code == 409


def test_emissao_e_revogacao_vao_para_a_auditoria_sem_a_chave() -> None:
    mundo = Mundo()
    emitida = mundo.emitir()
    mundo.cliente.post(f"{ROTA}/{emitida['id']}/revogar", headers=ADMIN)

    registros = {r.acao: r for r in mundo.registros()}

    for acao in ("chave.emitida", "chave.revogada"):
        r = registros[acao]
        assert (r.email, r.alvo_tipo, r.alvo_id, r.alvo_nome) == (
            "adm@redetv.com",
            "chave",
            emitida["id"],
            "Sistema Legado",
        )
        assert r.detalhes == {"escopos": ["criar", "ler"]}
        assert emitida["chave"] not in r.model_dump_json()
    registro = mundo.repositorio.obter(emitida["id"])
    assert registro is not None
    assert registro.hmac not in "".join(r.model_dump_json() for r in mundo.registros())


def test_auditoria_que_falha_desfaz_a_emissao_e_a_revogacao() -> None:
    mundo = Mundo()
    emitida = mundo.emitir()
    chave = {"X-API-Key": emitida["chave"]}

    def falhar(_registro: Any) -> None:
        raise RuntimeError("auditoria fora")

    mundo.auditoria.acrescentar = falhar  # type: ignore[assignment]
    cliente = TestClient(mundo.cliente.app, raise_server_exceptions=False)

    revogada = cliente.post(f"{ROTA}/{emitida['id']}/revogar", headers=ADMIN)
    nova = cliente.post(ROTA, json=PEDIDO, headers=ADMIN)

    assert revogada.status_code == 500
    assert mundo.cliente.get("/v1/jobs", headers=chave).status_code == 200
    assert nova.status_code == 500
    assert [r.revogada_em is None for r in mundo.repositorio.listar()].count(False) == 1


def test_sem_repositorio_de_chaves_as_rotas_dao_503() -> None:
    papeis = RepositorioDePapeisEmMemoria()
    papeis.salvar("adm", ["administrador"])
    cliente = TestClient(
        criar_app(
            VerificadorFalso({"admin": Usuario(uid="adm", email="a@redetv.com")}),
            RepositorioEmMemoria(),
            ArmazenamentoFalso(),
            papeis=papeis,
        )
    )

    assert cliente.get(ROTA, headers=ADMIN).status_code == 503
