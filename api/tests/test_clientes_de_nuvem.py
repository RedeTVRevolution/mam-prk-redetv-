"""Fábrica de sessão autenticada e transporte REST único (spec #602)."""

from typing import Any

import pytest

from api.clientes_de_nuvem import ESCOPO_DA_NUVEM, sessao_autenticada, transporte_rest
from api.eventos_do_job import URL_BASE as URL_DO_PUBSUB
from api.eventos_do_job import transporte_do_pubsub
from api.mac_kms import URL_BASE as URL_DO_KMS
from api.mac_kms import transporte_do_kms


class Resposta:
    def __init__(self, status: int, corpo: Any) -> None:
        self.status_code = status
        self._corpo = corpo

    def json(self) -> Any:
        if self._corpo is None:
            raise ValueError("sem JSON")
        return self._corpo


@pytest.fixture
def google(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Troca a autenticação do Google pelo nome qualificado, como os outros testes."""
    visto: dict[str, Any] = {
        "escopos": [],
        "pedidos": [],
        "resposta": Resposta(200, {}),
    }

    class Sessao:
        def __init__(self, credenciais: Any) -> None:
            visto["credenciais"] = credenciais

        def request(self, metodo: str, url: str, **argumentos: Any) -> Resposta:
            visto["pedidos"].append((metodo, url, argumentos))
            resposta: Resposta = visto["resposta"]
            return resposta

    def padrao(scopes: list[str]) -> tuple[str, str]:
        visto["escopos"].append(scopes)
        return "credenciais", "projeto"

    monkeypatch.setattr("google.auth.default", padrao)
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", Sessao)
    return visto


def test_a_sessao_nasce_na_hora_da_chamada_com_o_escopo_pedido(
    google: dict[str, Any],
) -> None:
    padrao = sessao_autenticada()
    outro = sessao_autenticada("https://www.googleapis.com/auth/bigquery")

    assert google["escopos"] == [
        [ESCOPO_DA_NUVEM],
        ["https://www.googleapis.com/auth/bigquery"],
    ]
    assert google["credenciais"] == "credenciais"
    assert padrao is not outro  # sem cache


def test_o_transporte_monta_a_url_e_devolve_status_e_json(
    google: dict[str, Any],
) -> None:
    google["resposta"] = Resposta(201, {"ok": True})

    status, corpo = transporte_rest("https://x.googleapis.com/v1", timeout_s=7)(
        "POST", "a/b:c", {"k": 1}
    )

    assert (status, corpo) == (201, {"ok": True})
    assert google["pedidos"] == [
        ("POST", "https://x.googleapis.com/v1/a/b:c", {"json": {"k": 1}, "timeout": 7})
    ]


def test_resposta_sem_json_vira_corpo_vazio(google: dict[str, Any]) -> None:
    google["resposta"] = Resposta(204, None)

    assert transporte_rest("https://x")("DELETE", "a", None) == (204, {})


def test_pubsub_e_kms_usam_o_transporte_unico_com_escopo_e_timeout_deles(
    google: dict[str, Any],
) -> None:
    transporte_do_pubsub(5)("POST", "t:publish", {})
    transporte_do_kms()("GET", "chave", None)

    assert google["escopos"] == [
        ["https://www.googleapis.com/auth/pubsub"],
        [ESCOPO_DA_NUVEM],
    ]
    assert [(m, u, a["timeout"]) for m, u, a in google["pedidos"]] == [
        ("POST", f"{URL_DO_PUBSUB}/t:publish", 5),
        ("GET", f"{URL_DO_KMS}/chave", 30),
    ]


def test_personificar_troca_as_credenciais_pela_da_conta_dada(
    google: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    visto: dict[str, Any] = {}

    def personificadas(**kwargs: Any) -> str:
        visto.update(kwargs)
        return "da conta"

    monkeypatch.setattr(
        "google.auth.impersonated_credentials.Credentials", personificadas
    )

    sessao_autenticada(personificar="conta@exemplo")

    assert google["credenciais"] == "da conta"
    assert visto["source_credentials"] == "credenciais"
    assert visto["target_principal"] == "conta@exemplo"
    assert visto["target_scopes"] == [ESCOPO_DA_NUVEM]
