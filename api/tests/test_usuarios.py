from datetime import UTC, datetime
from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient

from api.auditoria import (
    FiltroDeAuditoria,
    RegistroDeAuditoria,
    RepositorioDeAuditoriaEmMemoria,
)
from api.auth import Usuario
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.nuvem import ContasIdentityPlatform
from api.papeis import Papel, RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_jobs import ArmazenamentoFalso
from api.usuarios import (
    ContaDoIdentityPlatform,
    ContasDeUsuarioEmMemoria,
    EmailJaCadastrado,
)

AGORA = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
ADMIN = {"Authorization": "Bearer admin"}
ROTA = "/v1/admin/usuarios"


class Mundo:
    def __init__(
        self,
        papeis_do_admin: list[Papel] | None = None,
        auditoria: RepositorioDeAuditoriaEmMemoria | None = None,
    ) -> None:
        self.papeis = RepositorioDePapeisEmMemoria()
        self.papeis.salvar("adm", papeis_do_admin or ["administrador"])
        self.papeis.salvar("u2", ["editor"])
        self.contas = ContasDeUsuarioEmMemoria(
            [
                ContaDoIdentityPlatform(
                    uid="adm", email="adm@redetv.com", nome="Adm", email_verificado=True
                ),
                ContaDoIdentityPlatform(
                    uid="u2",
                    email="bia@redetv.com",
                    nome="Bia",
                    email_verificado=True,
                    criada_em=AGORA,
                    ultimo_acesso=AGORA,
                ),
            ]
        )
        self.auditoria = auditoria or RepositorioDeAuditoriaEmMemoria()
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "admin": Usuario(uid="adm", email="Adm@redetv.com"),
                        "bia": Usuario(uid="u2", email="bia@redetv.com"),
                    }
                ),
                RepositorioEmMemoria(),
                ArmazenamentoFalso(),
                papeis=self.papeis,
                auditoria=self.auditoria,
                contas=self.contas,
                relogio=lambda: AGORA,
            )
        )

    def registros(self) -> list[Any]:
        return self.auditoria.consultar(FiltroDeAuditoria()).registros


def test_lista_as_contas_com_papeis_e_situacao() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.get(ROTA, headers=ADMIN)

    assert resposta.status_code == 200
    assert resposta.json() == [
        {
            "uid": "adm",
            "email": "adm@redetv.com",
            "nome": "Adm",
            "papeis": ["administrador"],
            "criada_em": None,
            "ultimo_acesso": None,
            "situacao": "ativa",
        },
        {
            "uid": "u2",
            "email": "bia@redetv.com",
            "nome": "Bia",
            "papeis": ["editor"],
            "criada_em": "2026-11-02T12:00:00Z",
            "ultimo_acesso": "2026-11-02T12:00:00Z",
            "situacao": "ativa",
        },
    ]


def test_cria_a_conta_com_papeis_manda_o_link_e_audita() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.post(
        ROTA,
        json={
            "email": "cris@redetv.com",
            "nome": "Cris",
            "papeis": ["operador", "consulta"],
        },
        headers=ADMIN,
    )

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["email"] == "cris@redetv.com"
    assert corpo["papeis"] == ["consulta", "operador"]
    assert mundo.contas.links_enviados == ["cris@redetv.com"]
    assert mundo.papeis.obter(corpo["uid"]) == ["consulta", "operador"]
    (registro,) = mundo.registros()
    assert (
        registro.acao,
        registro.alvo_tipo,
        registro.alvo_id,
        registro.alvo_nome,
    ) == (
        "conta.criada",
        "usuario",
        corpo["uid"],
        "cris@redetv.com",
    )
    assert (registro.uid, registro.email) == ("adm", "adm@redetv.com")
    assert registro.detalhes == {"papeis": ["consulta", "operador"]}


def test_criar_com_e_mail_repetido_devolve_409_sem_registro() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.post(
        ROTA,
        json={"email": "BIA@redetv.com", "nome": "Outra", "papeis": ["consulta"]},
        headers=ADMIN,
    )

    assert resposta.status_code == 409
    assert mundo.registros() == []


@pytest.mark.parametrize(
    "corpo",
    [
        {"email": "sem-arroba", "nome": "X", "papeis": ["consulta"]},
        {"email": "x@y.z", "nome": " ", "papeis": ["consulta"]},
        {"email": "x@y.z", "nome": "X", "papeis": ["chefe"]},
    ],
)
def test_criar_recusa_pedido_invalido(corpo: dict[str, Any]) -> None:
    assert Mundo().cliente.post(ROTA, json=corpo, headers=ADMIN).status_code == 422


def test_reenvia_o_link_e_audita() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.post(f"{ROTA}/u2/link-de-senha", headers=ADMIN)

    assert resposta.status_code == 200
    assert mundo.contas.links_enviados == ["bia@redetv.com"]
    (registro,) = mundo.registros()
    assert (registro.acao, registro.alvo_id) == ("conta.link_reenviado", "u2")


def test_troca_os_papeis_e_guarda_antes_e_depois() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.put(
        f"{ROTA}/u2/papeis", json={"papeis": ["curador", "consulta"]}, headers=ADMIN
    )

    assert resposta.status_code == 200
    assert resposta.json()["papeis"] == ["consulta", "curador"]
    assert mundo.papeis.obter("u2") == ["consulta", "curador"]
    (registro,) = mundo.registros()
    assert registro.acao == "papeis.alterados"
    assert registro.detalhes == {
        "antes": ["editor"],
        "depois": ["consulta", "curador"],
    }


def test_da_o_papel_diretoria() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.put(
        f"{ROTA}/u2/papeis", json={"papeis": ["diretoria"]}, headers=ADMIN
    )

    assert resposta.status_code == 200
    assert mundo.papeis.obter("u2") == ["diretoria"]


def test_salvar_os_mesmos_papeis_em_outra_ordem_nao_grava_nem_audita() -> None:
    mundo = Mundo()
    mundo.papeis.salvar("u2", ["editor", "operador"])

    resposta = mundo.cliente.put(
        f"{ROTA}/u2/papeis", json={"papeis": ["operador", "editor"]}, headers=ADMIN
    )

    assert resposta.status_code == 200
    assert mundo.papeis.obter("u2") == ["editor", "operador"]
    assert mundo.registros() == []


def test_ninguem_tira_de_si_o_papel_de_administrador() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.put(
        f"{ROTA}/adm/papeis", json={"papeis": ["curador"]}, headers=ADMIN
    )

    assert resposta.status_code == 409
    assert "Administrador" in resposta.json()["detail"]
    assert mundo.papeis.obter("adm") == ["administrador"]
    assert mundo.registros() == []


def test_pode_trocar_os_proprios_papeis_mantendo_o_de_administrador() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.put(
        f"{ROTA}/adm/papeis",
        json={"papeis": ["administrador", "curador"]},
        headers=ADMIN,
    )

    assert resposta.status_code == 200


def test_admin_de_emergencia_segue_administrador_apos_trocar_papeis() -> None:
    mundo = Mundo()
    mundo.contas.criar("emerg@redetv.com", "Emerg")
    app = criar_app(
        VerificadorFalso({"admin": Usuario(uid="adm", email="adm@redetv.com")}),
        RepositorioEmMemoria(),
        ArmazenamentoFalso(),
        papeis=mundo.papeis,
        admins_emergencia="emerg@redetv.com",
        auditoria=mundo.auditoria,
        contas=mundo.contas,
    )
    cliente = TestClient(app)

    cliente.put(f"{ROTA}/uid-3/papeis", json={"papeis": ["consulta"]}, headers=ADMIN)

    lista = {u["uid"]: u["papeis"] for u in cliente.get(ROTA, headers=ADMIN).json()}
    assert lista["uid-3"] == ["consulta", "administrador"]
    assert mundo.registros() == []


def test_admin_de_emergencia_pode_trocar_os_proprios_papeis_sem_o_administrador() -> (
    None
):
    mundo = Mundo()
    conta = mundo.contas.criar("emerg@redetv.com", "Emerg")
    cliente = TestClient(
        criar_app(
            VerificadorFalso(
                {
                    "emerg": Usuario(
                        uid=conta.uid, email="emerg@redetv.com", email_verificado=True
                    )
                }
            ),
            RepositorioEmMemoria(),
            ArmazenamentoFalso(),
            papeis=mundo.papeis,
            admins_emergencia="emerg@redetv.com",
            auditoria=mundo.auditoria,
            contas=mundo.contas,
        )
    )

    resposta = cliente.put(
        f"{ROTA}/{conta.uid}/papeis",
        json={"papeis": ["curador"]},
        headers={"Authorization": "Bearer emerg"},
    )

    assert resposta.status_code == 200
    assert resposta.json()["papeis"] == ["curador", "administrador"]
    assert mundo.papeis.obter(conta.uid) == ["curador"]


class AuditoriaQueFalha(RepositorioDeAuditoriaEmMemoria):
    def acrescentar(self, registro: RegistroDeAuditoria) -> None:
        raise RuntimeError("Firestore fora")


def test_sem_auditoria_os_papeis_voltam_ao_que_eram() -> None:
    mundo = Mundo(auditoria=AuditoriaQueFalha())

    with pytest.raises(RuntimeError):
        mundo.cliente.put(
            f"{ROTA}/u2/papeis", json={"papeis": ["consulta"]}, headers=ADMIN
        )

    assert mundo.papeis.obter("u2") == ["editor"]


def test_sem_auditoria_a_conta_nao_fica_desativada() -> None:
    mundo = Mundo(auditoria=AuditoriaQueFalha())

    with pytest.raises(RuntimeError):
        mundo.cliente.post(f"{ROTA}/u2/desativar", headers=ADMIN)

    assert not mundo.papeis.desativada("u2")
    assert not mundo.contas.obter("u2").bloqueada  # type: ignore[union-attr]


def test_desativar_corta_o_acesso_na_hora_mesmo_com_token_valido() -> None:
    mundo = Mundo()
    bia = {"Authorization": "Bearer bia"}
    assert mundo.cliente.get("/v1/eu", headers=bia).status_code == 200

    resposta = mundo.cliente.post(f"{ROTA}/u2/desativar", headers=ADMIN)

    assert resposta.status_code == 200
    assert resposta.json()["situacao"] == "desativada"
    assert mundo.cliente.get("/v1/eu", headers=bia).status_code == 401
    assert mundo.papeis.desativada("u2")
    assert mundo.contas.obter("u2").bloqueada  # type: ignore[union-attr]
    assert mundo.contas.sessoes_revogadas == ["u2"]
    (registro,) = mundo.registros()
    assert (registro.acao, registro.alvo_id) == ("conta.desativada", "u2")
    # A conta continua na lista, e os papéis, guardados.
    lista = mundo.cliente.get(ROTA, headers=ADMIN).json()
    assert [(u["uid"], u["situacao"]) for u in lista] == [
        ("adm", "ativa"),
        ("u2", "desativada"),
    ]
    assert mundo.papeis.obter("u2") == ["editor"]


def test_reativar_devolve_o_acesso() -> None:
    mundo = Mundo()
    bia = {"Authorization": "Bearer bia"}
    mundo.cliente.post(f"{ROTA}/u2/desativar", headers=ADMIN)

    resposta = mundo.cliente.post(f"{ROTA}/u2/reativar", headers=ADMIN)

    assert resposta.json()["situacao"] == "ativa"
    assert mundo.cliente.get("/v1/eu", headers=bia).status_code == 200
    # O relógio é fixo: a ordem entre os dois registros fica ao acaso.
    assert sorted(r.acao for r in mundo.registros()) == [
        "conta.desativada",
        "conta.reativada",
    ]


def test_ninguem_desativa_a_si_mesmo() -> None:
    mundo = Mundo()

    resposta = mundo.cliente.post(f"{ROTA}/adm/desativar", headers=ADMIN)

    assert resposta.status_code == 409
    assert "própria conta" in resposta.json()["detail"]
    assert not mundo.papeis.desativada("adm")
    assert mundo.registros() == []


@pytest.mark.parametrize(
    ("metodo", "caminho"),
    [
        ("post", "/zzz/link-de-senha"),
        ("put", "/zzz/papeis"),
        ("post", "/zzz/desativar"),
        ("post", "/zzz/reativar"),
    ],
)
def test_conta_desconhecida_devolve_404(metodo: str, caminho: str) -> None:
    mundo = Mundo()

    resposta = getattr(mundo.cliente, metodo)(
        ROTA + caminho,
        headers=ADMIN,
        **({"json": {"papeis": []}} if metodo == "put" else {}),
    )

    assert resposta.status_code == 404
    assert mundo.registros() == []


@pytest.mark.parametrize(
    "papeis", [["consulta"], ["operador"], ["editor"], ["curador"], ["diretoria"]]
)
def test_sem_usuarios_gerir_devolve_403_em_toda_rota(papeis: list[Papel]) -> None:
    mundo = Mundo(papeis)
    pedidos = [
        ("get", "", None),
        ("post", "", {"email": "x@y.z", "nome": "X", "papeis": ["consulta"]}),
        ("post", "/u2/link-de-senha", None),
        ("put", "/u2/papeis", {"papeis": ["consulta"]}),
        ("post", "/u2/desativar", None),
        ("post", "/u2/reativar", None),
    ]

    for metodo, caminho, corpo in pedidos:
        resposta = getattr(mundo.cliente, metodo)(
            ROTA + caminho, headers=ADMIN, **({"json": corpo} if corpo else {})
        )
        assert resposta.status_code == 403, (metodo, caminho)
    assert mundo.registros() == []
    assert not mundo.papeis.desativada("u2")


def test_so_o_administrador_tem_usuarios_gerir() -> None:
    from api.papeis import PERMISSOES_DO_PAPEL

    com = [p for p, perm in PERMISSOES_DO_PAPEL.items() if "usuarios.gerir" in perm]
    assert com == ["administrador"]


class RespostaFalsa:
    def __init__(self, corpo: dict[str, Any] | None = None, ok: bool = True) -> None:
        self._corpo = corpo or {}
        self.ok = ok
        self.content = b"{}" if corpo is not None else b""
        self.text = str(self._corpo)

    def json(self) -> dict[str, Any]:
        return self._corpo


class SessaoFalsa:
    def __init__(self, *respostas: RespostaFalsa) -> None:
        self.respostas = list(respostas)
        self.pedidos: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, metodo: str, url: str, **argumentos: Any) -> RespostaFalsa:
        self.pedidos.append((metodo, url, argumentos))
        return self.respostas.pop(0)


def test_contas_do_identity_platform_leem_a_lista_paginada() -> None:
    sessao = SessaoFalsa(
        RespostaFalsa(
            {
                "users": [
                    {
                        "localId": "a",
                        "email": "a@x.y",
                        "displayName": "A",
                        "emailVerified": True,
                        "createdAt": "1793620800000",
                        "lastLoginAt": "0",
                        "disabled": True,
                    }
                ],
                "nextPageToken": "p2",
            }
        ),
        RespostaFalsa({"users": [{"localId": "b", "email": "b@x.y"}]}),
    )

    contas = ContasIdentityPlatform("proj", sessao).listar()

    assert [(c.uid, c.nome, c.bloqueada) for c in contas] == [
        ("a", "A", True),
        ("b", "", False),
    ]
    assert contas[0].criada_em == datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    assert contas[0].ultimo_acesso is None
    assert sessao.pedidos[1][2]["params"]["nextPageToken"] == "p2"
    assert sessao.pedidos[0][1].endswith("/projects/proj/accounts:batchGet")


def test_contas_do_identity_platform_bloquear_revoga_os_tokens() -> None:
    sessao = SessaoFalsa(RespostaFalsa({}), RespostaFalsa({}))
    contas = ContasIdentityPlatform("proj", sessao)

    contas.bloquear("u2", True)
    contas.bloquear("u2", False)

    assert sessao.pedidos[0][2]["json"]["disableUser"] is True
    assert "validSince" in sessao.pedidos[0][2]["json"]
    assert sessao.pedidos[1][2]["json"] == {"localId": "u2", "disableUser": False}


def test_contas_do_identity_platform_criar_com_e_mail_existente() -> None:
    sessao = SessaoFalsa(RespostaFalsa({"error": "EMAIL_EXISTS"}, ok=False))

    with pytest.raises(EmailJaCadastrado):
        ContasIdentityPlatform("proj", sessao).criar("a@x.y", "A")


def test_contas_do_identity_platform_repassa_outras_falhas() -> None:
    sessao = SessaoFalsa(RespostaFalsa({"error": "QUOTA"}, ok=False))

    with pytest.raises(requests.HTTPError):
        ContasIdentityPlatform("proj", sessao).enviar_link_de_senha("a@x.y")
