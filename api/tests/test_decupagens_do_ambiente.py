"""O leitor de Decupagens montado do ambiente (#639): um só jeito nos 13 pontos de entrada."""

import pytest

from api import nuvem
from api.ambiente import FaltaNoAmbiente
from api.nuvem import DecupagensStorage

AMBIENTE = {
    "GCP_PROJECT_ID": "projeto",
    "BUCKET_ACEITOS": "aceitos",
    "BUCKET_DECUPAGENS": "decupagens",
}


class ClienteFalso:
    def __init__(self, project: str | None = None) -> None:
        self.project = project
        self.buckets: list[str] = []

    def bucket(self, nome: str) -> "ClienteFalso":
        self.buckets.append(nome)
        return self

    def blob(self, _nome: str) -> "ClienteFalso":
        return self


def test_lê_os_três_nomes_e_cria_o_cliente_do_projeto(monkeypatch) -> None:
    criados: list[ClienteFalso] = []

    def criar(project: str) -> ClienteFalso:
        criados.append(ClienteFalso(project))
        return criados[0]

    monkeypatch.setattr(nuvem, "ClienteStorage", criar)
    leitor = DecupagensStorage.do_ambiente(AMBIENTE)
    assert [c.project for c in criados] == ["projeto"]
    assert leitor.uri_do_proxy("j1").startswith("gs://aceitos/")
    assert leitor._decupagens == "decupagens"


def test_reaproveita_o_cliente_dado(monkeypatch) -> None:
    monkeypatch.setattr(
        nuvem, "ClienteStorage", lambda **_: pytest.fail("criou outro cliente")
    )
    cliente = ClienteFalso()
    assert DecupagensStorage.do_ambiente(AMBIENTE, cliente)._cliente is cliente


@pytest.mark.parametrize("nome", list(AMBIENTE))
def test_falta_levanta_com_o_nome_que_falta(nome: str) -> None:
    ambiente = {k: v for k, v in AMBIENTE.items() if k != nome}
    with pytest.raises(FaltaNoAmbiente, match=f"{nome} não está no ambiente"):
        DecupagensStorage.do_ambiente(ambiente, ClienteFalso())
