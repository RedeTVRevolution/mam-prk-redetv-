"""Cadastro de marcas do Curador: apelidos e juntar duas marcas (`/v1/catalogo/marcas/...`)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.auditoria import RepositorioDeAuditoriaEmMemoria
from api.auth import Usuario
from api.catalogo import EnvioParaLixeira
from api.jobs import RepositorioEmMemoria
from api.main import criar_app
from api.marcas import CatalogoDeMarcasEmMemoria, MarcaInexistente
from api.papeis import RepositorioDePapeisEmMemoria
from api.tests.test_auth import VerificadorFalso
from api.tests.test_correcoes import BASE

CURADOR = {"Authorization": "Bearer curador"}
EDITOR = {"Authorization": "Bearer editor"}
CADASTRO = "/v1/catalogo/marcas/cadastro"
ENVIO = EnvioParaLixeira(
    em=BASE, por_uid="cur", por_email="cura@redetv.com.br", motivo="teste"
)


class Mundo:
    def __init__(self) -> None:
        papeis = RepositorioDePapeisEmMemoria()
        papeis.salvar("cur", ["curador"])
        papeis.salvar("edi", ["editor"])
        self.marcas = CatalogoDeMarcasEmMemoria()
        self.auditoria = RepositorioDeAuditoriaEmMemoria()
        self.cliente = TestClient(
            criar_app(
                VerificadorFalso(
                    {
                        "curador": Usuario(uid="cur", email="cura@redetv.com.br"),
                        "editor": Usuario(uid="edi", email="edi@redetv.com.br"),
                    }
                ),
                RepositorioEmMemoria(),
                papeis=papeis,
                marcas=self.marcas,
                auditoria=self.auditoria,
                relogio=lambda: BASE,
            )
        )

    def get(self, url: str, quem: dict[str, str] = CURADOR) -> Any:
        return self.cliente.get(url, headers=quem)

    def post(
        self, url: str, corpo: dict[str, Any], quem: dict[str, str] = CURADOR
    ) -> Any:
        return self.cliente.post(url, json=corpo, headers=quem)

    def put(
        self, url: str, corpo: dict[str, Any], quem: dict[str, str] = CURADOR
    ) -> Any:
        return self.cliente.put(url, json=corpo, headers=quem)

    def acoes(self) -> list[str]:
        return [r.acao for r in self.auditoria._registros.values()]


def test_lista_fora_da_lixeira_ordenada_por_nome_sem_caixa_nem_acento() -> None:
    m = Mundo()
    m.marcas.acrescentar("Zeca", [])
    m.marcas.acrescentar("Ágil", ["Agil Ltda"])
    na_lixeira = m.marcas.acrescentar("Banco", [])
    m.marcas.definir_lixeira(na_lixeira.id, ENVIO)
    m.marcas.acrescentar("beta", [])

    resposta = m.get(CADASTRO)

    assert resposta.status_code == 200
    assert [(x["nome"], x["apelidos"]) for x in resposta.json()] == [
        ("Ágil", ["Agil Ltda"]),
        ("beta", []),
        ("Zeca", []),
    ]
    assert set(resposta.json()[0]) == {"id", "nome", "apelidos"}


def test_cria_a_marca_com_apelidos_e_grava_auditoria() -> None:
    m = Mundo()

    resposta = m.post(CADASTRO, {"nome": "UNIFAEL", "apelidos": ["UniAefel"]})

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert (corpo["nome"], corpo["apelidos"]) == ("UNIFAEL", ["UniAefel"])
    assert m.marcas.obter(corpo["id"]) is not None
    assert m.acoes() == ["marca.criada"]


def test_criar_descarta_apelido_repetido_em_silencio_e_exige_o_nome() -> None:
    m = Mundo()

    resposta = m.post(
        CADASTRO,
        {
            "nome": "RedeTV Go",
            "apelidos": ["RedeTV! GO", "Go App", "go-app", "GO APP!"],
        },
    )

    # "RedeTV! GO" é o próprio nome; as três de "Go App" têm a mesma chave.
    assert resposta.json()["apelidos"] == ["Go App"]
    assert m.post(CADASTRO, {"nome": "  ", "apelidos": []}).status_code == 422
    assert m.post(CADASTRO, {"apelidos": []}).status_code == 422


def test_criar_com_nome_ou_apelido_de_outra_marca_e_409_e_manda_juntar() -> None:
    m = Mundo()
    m.marcas.acrescentar("UniAefel", [])
    m.marcas.acrescentar("Natura", ["Natura Cosméticos"])

    pelo_nome = m.post(CADASTRO, {"nome": "UniAefel", "apelidos": []})
    pelo_apelido = m.post(
        CADASTRO, {"nome": "Nova", "apelidos": ["natura cosmeticos!"]}
    )

    assert pelo_nome.status_code == 409
    assert pelo_nome.json()["detail"] == "UniAefel já é a marca UniAefel: use Juntar"
    assert pelo_apelido.status_code == 409
    assert "Natura" in pelo_apelido.json()["detail"]
    assert len(m.marcas.todas()) == 2


def test_conflito_com_marca_na_lixeira_tambem_e_409() -> None:
    m = Mundo()
    velha = m.marcas.acrescentar("Velha", ["Antiga"])
    m.marcas.definir_lixeira(velha.id, ENVIO)

    resposta = m.post(CADASTRO, {"nome": "Antiga", "apelidos": []})

    assert resposta.status_code == 409
    assert "lixeira" in resposta.json()["detail"]


def test_troca_os_apelidos_da_marca_e_grava_auditoria() -> None:
    m = Mundo()
    marca = m.marcas.acrescentar("UNIFAEL", ["Antigo"])

    resposta = m.put(
        f"/v1/catalogo/marcas/{marca.id}/apelidos",
        {"apelidos": ["UniAefel", "unifael!", "Uni"]},
    )

    assert resposta.status_code == 200
    assert resposta.json() == {
        "id": marca.id,
        "nome": "UNIFAEL",
        "apelidos": ["UniAefel", "Uni"],  # "unifael!" é o próprio nome
    }
    assert m.marcas.achar("uniaefel")[0].id == marca.id  # nomes de busca ao dia
    assert m.marcas.achar("antigo") == []
    assert m.acoes() == ["marca.alterada"]


def test_apelido_de_outra_marca_no_put_e_409_mas_o_da_propria_nao() -> None:
    m = Mundo()
    uma = m.marcas.acrescentar("UNIFAEL", ["UniAefel"])
    m.marcas.acrescentar("Natura", ["Nat"])

    do_outro = m.put(f"/v1/catalogo/marcas/{uma.id}/apelidos", {"apelidos": ["nat."]})
    do_proprio = m.put(
        f"/v1/catalogo/marcas/{uma.id}/apelidos", {"apelidos": ["UniAefel", "Outro"]}
    )

    assert do_outro.status_code == 409
    assert "Natura" in do_outro.json()["detail"]
    assert do_proprio.status_code == 200
    assert m.marcas.obter(uma.id).apelidos == ["UniAefel", "Outro"]  # type: ignore[union-attr]


def test_put_de_marca_inexistente_ou_na_lixeira_e_404() -> None:
    m = Mundo()
    velha = m.marcas.acrescentar("Velha", [])
    m.marcas.definir_lixeira(velha.id, ENVIO)

    assert (
        m.put("/v1/catalogo/marcas/nao-existe/apelidos", {"apelidos": []}).status_code
        == 404
    )
    assert (
        m.put(f"/v1/catalogo/marcas/{velha.id}/apelidos", {"apelidos": []}).status_code
        == 404
    )


def test_limites_dos_apelidos_como_nos_do_programa() -> None:
    m = Mundo()
    marca = m.marcas.acrescentar("Nike", [])
    url = f"/v1/catalogo/marcas/{marca.id}/apelidos"

    assert m.put(url, {"apelidos": [f"a{i}" for i in range(21)]}).status_code == 422
    assert m.put(url, {"apelidos": ["x" * 101]}).status_code == 422
    assert m.put(url, {"apelidos": ["a\x00b"]}).status_code == 422
    assert m.put(url, {"apelidos": ["  "]}).status_code == 422


def test_juntar_passa_nome_e_apelidos_da_outra_e_apaga_a_outra() -> None:
    m = Mundo()
    destino = m.marcas.acrescentar("UNIFAEL", ["Unifael Ltda"])
    outra = m.marcas.acrescentar("UniAefel", ["uni aefel", "UNIFAEL!"])

    resposta = m.post(
        f"/v1/catalogo/marcas/{destino.id}/juntar", {"outra_id": outra.id}
    )

    assert resposta.status_code == 200
    assert resposta.json() == {
        "id": destino.id,
        "nome": "UNIFAEL",
        "apelidos": ["Unifael Ltda", "UniAefel"],  # sem repetir a chave
    }
    assert m.marcas.obter(outra.id) is None
    assert m.marcas.achar("uniaefel")[0].id == destino.id
    assert m.acoes() == ["marca.juntada"]


@pytest.mark.parametrize(
    ("destino_existe", "outra_existe", "status"),
    [(False, True, 404), (True, False, 404)],
)
def test_juntar_com_marca_inexistente_e_404(
    destino_existe: bool, outra_existe: bool, status: int
) -> None:
    m = Mundo()
    uma = m.marcas.acrescentar("Uma", [])
    outra = m.marcas.acrescentar("Outra", [])
    destino_id = uma.id if destino_existe else "nao-existe"
    outra_id = outra.id if outra_existe else "nao-existe"

    resposta = m.post(
        f"/v1/catalogo/marcas/{destino_id}/juntar", {"outra_id": outra_id}
    )

    assert resposta.status_code == status


def test_juntar_a_mesma_ou_a_da_lixeira_e_409() -> None:
    m = Mundo()
    uma = m.marcas.acrescentar("Uma", [])
    velha = m.marcas.acrescentar("Velha", [])
    m.marcas.definir_lixeira(velha.id, ENVIO)

    mesma = m.post(f"/v1/catalogo/marcas/{uma.id}/juntar", {"outra_id": uma.id})
    da_lixeira = m.post(f"/v1/catalogo/marcas/{uma.id}/juntar", {"outra_id": velha.id})

    assert mesma.status_code == 409
    assert da_lixeira.status_code == 409
    assert m.marcas.obter(velha.id) is not None


def test_juntar_com_apelidos_demais_nao_muda_nada() -> None:
    m = Mundo()
    destino = m.marcas.acrescentar("Uma", [f"a{i}" for i in range(15)])
    outra = m.marcas.acrescentar("Outra", [f"b{i}" for i in range(15)])

    resposta = m.post(
        f"/v1/catalogo/marcas/{destino.id}/juntar", {"outra_id": outra.id}
    )

    assert resposta.status_code == 422
    assert m.marcas.obter(outra.id) is not None
    assert len(m.marcas.obter(destino.id).apelidos) == 15  # type: ignore[union-attr]


def test_editor_nao_mexe_no_cadastro() -> None:
    m = Mundo()
    marca = m.marcas.acrescentar("Nike", [])
    outra = m.marcas.acrescentar("Nik", [])

    respostas = [
        m.get(CADASTRO, EDITOR),
        m.post(CADASTRO, {"nome": "X", "apelidos": []}, EDITOR),
        m.put(f"/v1/catalogo/marcas/{marca.id}/apelidos", {"apelidos": ["a"]}, EDITOR),
        m.post(
            f"/v1/catalogo/marcas/{marca.id}/juntar", {"outra_id": outra.id}, EDITOR
        ),
    ]

    assert [r.status_code for r in respostas] == [403, 403, 403, 403]
    assert m.acoes() == []


def test_o_autocompletar_ve_a_mudanca_na_hora() -> None:
    m = Mundo()
    marca = m.marcas.acrescentar("UNIFAEL", [])
    assert m.get("/v1/catalogo/marcas?q=uniaefel").json() == []  # esquenta a cópia

    m.put(f"/v1/catalogo/marcas/{marca.id}/apelidos", {"apelidos": ["UniAefel"]})

    assert [x["id"] for x in m.get("/v1/catalogo/marcas?q=uniaefel").json()] == [
        marca.id
    ]


def test_auditoria_que_falha_desfaz_a_mudanca() -> None:
    m = Mundo()
    marca = m.marcas.acrescentar("UNIFAEL", ["Antigo"])
    outra = m.marcas.acrescentar("UniAefel", [])

    def cai(*_: Any, **__: Any) -> None:
        raise RuntimeError("Firestore fora")

    m.auditoria.acrescentar = cai  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        m.put(f"/v1/catalogo/marcas/{marca.id}/apelidos", {"apelidos": ["Novo"]})
    with pytest.raises(RuntimeError):
        m.post(f"/v1/catalogo/marcas/{marca.id}/juntar", {"outra_id": outra.id})
    with pytest.raises(RuntimeError):
        m.post(CADASTRO, {"nome": "Nova", "apelidos": []})

    assert m.marcas.obter(marca.id).apelidos == ["Antigo"]  # type: ignore[union-attr]
    assert m.marcas.obter(outra.id) is not None
    assert [x.nome for x in m.marcas.todas()] == ["UNIFAEL", "UniAefel"]


def test_definir_apelidos_no_catalogo_em_memoria() -> None:
    marcas = CatalogoDeMarcasEmMemoria()
    marca = marcas.acrescentar("UNIFAEL", [])

    atualizada = marcas.definir_apelidos(marca.id, ["UniAefel"])

    assert atualizada.apelidos == ["UniAefel"]
    assert marcas.achar("uniaefel") == [atualizada]
    with pytest.raises(MarcaInexistente):
        marcas.definir_apelidos("nao-existe", [])
