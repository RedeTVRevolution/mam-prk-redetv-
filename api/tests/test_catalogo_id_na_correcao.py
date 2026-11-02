"""A correção que vem com o `catalogo_id` da pessoa ou da marca o grava (#150)."""

from typing import Any

from api.tests.test_catalogo_na_correcao import _pessoa
from api.tests.test_comerciais import VERSAO_COM, _mundo
from api.tests.test_correcoes import MODELO, Mundo


def _marca(mundo: Mundo, id: str = "com000") -> dict[str, Any]:
    return next(c for c in mundo.decupagem()["comerciais"] if c["id"] == id)


def _corrigir_marca(mundo: Mundo, valor: str, **campos: Any) -> Any:
    return mundo.corrigir(
        tipo="comercial.marca",
        item_id="com000",
        valor=valor,
        versao=VERSAO_COM,
        **campos,
    )


def test_pessoa_escolhida_grava_o_id_mesmo_com_dois_nomes_iguais() -> None:
    mundo = Mundo(["editor"])
    mundo.catalogo.acrescentar("Ana Souza Lima", "atriz", [])
    certa = mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])

    resposta = mundo.corrigir(catalogo_id=certa.id)

    assert resposta.status_code == 201
    assert _pessoa(mundo, "pes01")["catalogo_id"] == certa.id
    assert mundo.historico().json()[0]["catalogo_id"] == certa.id


def test_pessoa_escolhida_pelo_apelido() -> None:
    mundo = Mundo(["editor"])
    ana = mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", ["Aninha"])

    assert mundo.corrigir(valor="aninha", catalogo_id=ana.id).status_code == 201

    assert _pessoa(mundo, "pes01")["catalogo_id"] == ana.id


def test_id_que_nao_existe_ou_e_de_outro_nome_e_recusado() -> None:
    mundo = Mundo(["editor"])
    ana = mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])

    sem_ninguem = mundo.corrigir(catalogo_id="nao-existe")
    outro_nome = mundo.corrigir(valor="Fulano de Tal", catalogo_id=ana.id)

    assert (sem_ninguem.status_code, outro_nome.status_code) == (422, 422)
    assert mundo.historico().json() == []
    assert _pessoa(mundo, "pes01").get("catalogo_id") is None


def test_catalogo_id_so_vale_no_nome_de_pessoa_ou_de_marca() -> None:
    mundo = Mundo(["editor"])
    ana = mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])

    resposta = mundo.corrigir(
        tipo="pauta.titulo", item_id="pau01", valor="Outro", catalogo_id=ana.id
    )

    assert resposta.status_code == 422


def test_marca_escolhida_grava_o_id_na_decupagem_entregue() -> None:
    mundo = _mundo()
    banco = mundo.marcas.acrescentar("Banco Verde", ["BV"])

    resposta = _corrigir_marca(mundo, "Banco Verde", catalogo_id=banco.id)

    assert resposta.status_code == 201
    com = _marca(mundo)
    assert (com["marca"], com["catalogo_id"], com["origem"]) == (
        "Banco Verde",
        banco.id,
        "revisao",
    )
    assert _marca(mundo, "com001").get("catalogo_id") is None
    assert mundo.historico().json()[0]["catalogo_id"] == banco.id


def test_marca_sem_escolha_nao_grava_id_mesmo_que_o_nome_exista() -> None:
    mundo = _mundo()
    mundo.marcas.acrescentar("Banco Verde", [])

    _corrigir_marca(mundo, "Banco Verde")

    assert _marca(mundo).get("catalogo_id") is None


def test_marca_com_id_que_nao_existe_ou_de_outro_nome_e_recusada() -> None:
    mundo = _mundo()
    banco = mundo.marcas.acrescentar("Banco Verde", [])

    assert _corrigir_marca(mundo, "Banco Verde", catalogo_id="x").status_code == 422
    assert _corrigir_marca(mundo, "Loja Sol", catalogo_id=banco.id).status_code == 422
    assert mundo.historico().json() == []


def test_marca_trocada_ou_desfeita_nao_deixa_o_id_da_anterior() -> None:
    mundo = _mundo()
    banco = mundo.marcas.acrescentar("Banco Verde", [])
    cid = _corrigir_marca(mundo, "Banco Verde", catalogo_id=banco.id).json()["id"]

    mundo.avancar()
    _corrigir_marca(mundo, "Loja Sol")
    assert _marca(mundo).get("catalogo_id") is None

    mundo.avancar()
    mundo.desfazer(cid)
    assert _marca(mundo).get("catalogo_id") is None


def test_marca_com_id_resiste_ao_reprocessamento() -> None:
    mundo = _mundo()
    banco = mundo.marcas.acrescentar("Banco Verde", [])
    _corrigir_marca(mundo, "Banco Verde", catalogo_id=banco.id)

    novo = {
        **MODELO,
        "comerciais": [
            {
                "marca": "Banco Azul",
                "tipo": "patrocinio_vinheta",
                "inicio_ms": 10000,
                "fim_ms": 15000,
                "evidencias": ["logo"],
            }
        ],
    }
    mundo.reprocessar(novo)

    com = mundo.decupagem()["comerciais"][0]
    assert (com["marca"], com.get("catalogo_id")) == ("Banco Verde", banco.id)
