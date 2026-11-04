from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auditoria import FiltroDeAuditoria, RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.correcoes import CORRIGIVEIS, RepositorioDeAprovacaoEmMemoria
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso

AGORA = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
ADMIN = {"Authorization": "Bearer admin"}
ROTA = "/v1/admin/aprovacao"


class Mundo:
    def __init__(
        self, auditoria: RepositorioDeAuditoriaEmMemoria | None = None
    ) -> None:
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("adm", ["administrador"])
        papeis.salvar("cur", ["curador"])
        papeis.salvar("ed", ["editor"])
        self.repositorio = RepositorioDeAprovacaoEmMemoria()
        self.auditoria = auditoria or RepositorioDeAuditoriaEmMemoria()
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "admin": Usuario(uid="adm", email="adm@redetv.com"),
                        "curador": Usuario(uid="cur", email="cur@redetv.com"),
                        "editor": Usuario(uid="ed", email="ed@redetv.com"),
                    }
                ),
                RepositorioEmMemoria(),
                ArmazenamentoFalso(),
                papeis=papeis,
                auditoria=self.auditoria,
                aprovacao=self.repositorio,
                relogio=lambda: AGORA,
            ),
            raise_server_exceptions=False,
        )

    def mudar(self, tipo: str, exige: bool, quem: str = "admin") -> Any:
        return self.cliente.put(
            ROTA,
            json={"tipo": tipo, "exige_aprovacao": exige},
            headers={"Authorization": f"Bearer {quem}"},
        )

    def registros(self) -> list[Any]:
        return self.auditoria.consultar(FiltroDeAuditoria()).registros


def test_lista_todos_os_tipos_com_nome_e_nada_exige_aprovacao_por_padrao() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.get(ROTA, headers=ADMIN)

    assert resposta.status_code == 200
    regras = resposta.json()
    assert [r["tipo"] for r in regras] == list(CORRIGIVEIS)
    assert not any(r["exige_aprovacao"] for r in regras)
    renomear = next(r for r in regras if r["tipo"] == "pessoa.renomear")
    assert renomear["nome"] != "pessoa.renomear"


def test_ligar_e_desligar_vale_na_hora_e_a_lista_reflete() -> None:
    mundo = Mundo()

    ligada = mundo.mudar("pauta.titulo", True)
    assert ligada.status_code == 200
    assert mundo.repositorio.tipos() == {"pauta.titulo"}
    exigem = [r["tipo"] for r in ligada.json() if r["exige_aprovacao"]]
    assert exigem == ["pauta.titulo"]
    recarregada = mundo.cliente.get(ROTA, headers=ADMIN).json()
    assert [r["tipo"] for r in recarregada if r["exige_aprovacao"]] == ["pauta.titulo"]

    desligada = mundo.mudar("pauta.titulo", False)
    assert not any(r["exige_aprovacao"] for r in desligada.json())
    assert mundo.repositorio.tipos() == frozenset()


def test_cada_mudanca_vai_para_a_auditoria_com_o_antes_e_o_depois() -> None:
    mundo = Mundo()

    mundo.mudar("pauta.titulo", True)
    mundo.mudar("pauta.titulo", False)

    registros = sorted(mundo.registros(), key=lambda r: r.detalhes["depois"])
    assert [(r.detalhes["antes"], r.detalhes["depois"]) for r in registros] == [
        (True, False),
        (False, True),
    ]
    primeiro = registros[0]
    assert primeiro.acao == "aprovacao.alterada"
    assert primeiro.uid == "adm"
    assert primeiro.email == "adm@redetv.com"
    assert primeiro.alvo_tipo == "tipo_de_correcao"
    assert primeiro.alvo_id == "pauta.titulo"
    assert primeiro.alvo_nome != "pauta.titulo"


def test_repetir_o_mesmo_valor_nao_grava_auditoria() -> None:
    mundo = Mundo()

    resposta = mundo.mudar("pauta.titulo", False)

    assert resposta.status_code == 200
    assert mundo.registros() == []


def test_tipo_desconhecido_e_422_e_nao_grava() -> None:
    mundo = Mundo()

    resposta = mundo.mudar("pauta.foo", True)

    assert resposta.status_code == 422
    assert mundo.repositorio.tipos() == frozenset()
    assert mundo.registros() == []


@pytest.mark.parametrize("quem", ["curador", "editor"])
def test_quem_nao_e_administrador_recebe_403_em_get_e_put(quem: str) -> None:
    mundo = Mundo()
    cabecalho = {"Authorization": f"Bearer {quem}"}

    assert mundo.cliente.get(ROTA, headers=cabecalho).status_code == 403
    assert mundo.mudar("pauta.titulo", True, quem).status_code == 403
    assert mundo.repositorio.tipos() == frozenset()
    assert mundo.registros() == []


def test_sem_login_e_401() -> None:
    assert Mundo().cliente.get(ROTA).status_code == 401


def test_a_correcao_nova_passa_a_esperar_o_curador_e_a_pendente_continua() -> None:
    from api.tests.test_aprovacao import _estados
    from api.tests.test_correcoes import Mundo as MundoDeCorrecoes

    mundo = MundoDeCorrecoes(["editor"])
    antes = mundo.corrigir().json()["id"]
    mundo.aprovacao.definir(frozenset({"pessoa.renomear"}))
    depois = mundo.corrigir(valor="Ana Souza Lima Neto").json()["id"]
    mundo.aprovacao.definir(frozenset())

    assert _estados(mundo)[antes] == "ativa"
    assert _estados(mundo)[depois] == "pendente"


def test_falha_na_auditoria_desfaz_a_mudanca() -> None:
    class Quebrada(RepositorioDeAuditoriaEmMemoria):
        def acrescentar(self, registro: Any) -> None:
            raise RuntimeError("fora do ar")

    mundo = Mundo(Quebrada())
    mundo.repositorio.definir(frozenset({"pauta.tom"}))

    resposta = mundo.mudar("pauta.titulo", True)

    assert resposta.status_code == 500
    assert mundo.repositorio.tipos() == {"pauta.tom"}
