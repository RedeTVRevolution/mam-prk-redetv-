"""Autocompletar de pessoas e marcas, e nome novo "a revisar" (#150)."""

from typing import Any

import pytest

from api.tests.test_correcoes import AUTORIZACAO, Mundo

URL_PESSOAS = "/v1/catalogo/pessoas"
URL_MARCAS = "/v1/catalogo/marcas"


def _buscar(mundo: Mundo, url: str, q: str) -> Any:
    return mundo.cliente.get(url, params={"q": q}, headers=AUTORIZACAO)


def _nomes(mundo: Mundo, url: str, q: str) -> list[str]:
    resposta = _buscar(mundo, url, q)
    assert resposta.status_code == 200
    return [p["nome"] for p in resposta.json()]


def _mundo_com_pessoas() -> Mundo:
    mundo = Mundo(["editor"])
    mundo.catalogo.acrescentar("Sabrina Sato", "apresentadora", ["Sabrininha"])
    mundo.catalogo.acrescentar("Leão Lobo", "comentarista", [])
    mundo.catalogo.acrescentar("Ana Maria Braga", "apresentadora", [])
    return mundo


@pytest.mark.parametrize(
    ("consulta", "esperado"),
    [
        ("sabrin", ["Sabrina Sato"]),  # prefixo de palavra
        ("SATO", ["Sabrina Sato"]),  # a segunda palavra, em maiúsculas
        ("leao", ["Leão Lobo"]),  # sem acento
        ("LEÃO lo", ["Leão Lobo"]),  # vários termos, acento e maiúscula
        ("sabrininha", ["Sabrina Sato"]),  # apelido
        ("braga", ["Ana Maria Braga"]),
        ("sabrnia", ["Sabrina Sato"]),  # erro de digitação, termo de 7 letras
        ("sabrinx", ["Sabrina Sato"]),  # letra trocada
        ("abrina", ["Sabrina Sato"]),  # letra a menos no começo
        ("sabrinna", ["Sabrina Sato"]),  # letra a mais
        ("sab", ["Sabrina Sato"]),
        ("xyz", []),
    ],
)
def test_pessoas_por_prefixo_acento_maiuscula_apelido_e_erro(
    consulta: str, esperado: list[str]
) -> None:
    assert _nomes(_mundo_com_pessoas(), URL_PESSOAS, consulta) == esperado


def test_erro_de_digitacao_so_vale_com_5_letras_ou_mais() -> None:
    mundo = Mundo(["editor"])
    mundo.catalogo.acrescentar("Ana Lima", "repórter", [])
    mundo.catalogo.acrescentar("Rita Lima", "repórter", [])

    assert _nomes(mundo, URL_PESSOAS, "lmia") == []  # 4 letras: sem tolerância
    assert _nomes(mundo, URL_PESSOAS, "lmiaa") == []  # 2 erros
    assert _nomes(mundo, URL_PESSOAS, "rtia") == []
    assert _nomes(mundo, URL_PESSOAS, "ritas") == ["Rita Lima"]  # 5 letras: 1 erro


def test_o_prefixo_vem_antes_do_erro_de_digitacao() -> None:
    mundo = Mundo(["editor"])
    mundo.catalogo.acrescentar("Marina Alves", "repórter", [])
    mundo.catalogo.acrescentar("Marinho Costa", "repórter", [])

    assert _nomes(mundo, URL_PESSOAS, "marina") == ["Marina Alves", "Marinho Costa"]


def test_o_resultado_traz_id_nome_papel_e_o_rotulo() -> None:
    mundo = _mundo_com_pessoas()
    sabrina = mundo.catalogo.achar("Sabrina Sato")[0]

    [achada] = _buscar(mundo, URL_PESSOAS, "sabrina").json()

    assert achada == {
        "id": sabrina.id,
        "nome": "Sabrina Sato",
        "papel": "apresentadora",
        "rotulo": "Sabrina Sato (apresentadora)",
        "a_revisar": False,
    }


def test_no_maximo_10_pessoas() -> None:
    mundo = Mundo(["editor"])
    for i in range(15):
        mundo.catalogo.acrescentar(f"Maria {i:02d}", "repórter", [])

    nomes = _nomes(mundo, URL_PESSOAS, "mar")

    assert len(nomes) == 10
    assert nomes == [f"Maria {i:02d}" for i in range(10)]


def test_consulta_vazia_nao_acha_ninguem() -> None:
    assert _nomes(_mundo_com_pessoas(), URL_PESSOAS, "  ") == []


def test_sem_decupagem_ver_nao_busca() -> None:
    mundo = Mundo([])

    assert _buscar(mundo, URL_PESSOAS, "a").status_code == 403
    assert _buscar(mundo, URL_MARCAS, "a").status_code == 403


def test_sem_token_nao_busca() -> None:
    resposta = Mundo(["editor"]).cliente.get(URL_PESSOAS, params={"q": "a"})

    assert resposta.status_code == 401


def test_nome_novo_entra_a_revisar_com_o_autor_e_ja_aparece_na_busca() -> None:
    mundo = _mundo_com_pessoas()
    assert _nomes(mundo, URL_PESSOAS, "zeca") == []  # enche a cópia curta

    resposta = mundo.cliente.post(
        URL_PESSOAS,
        json={"nome": "  Zeca Pagodinho ", "papel": "cantor"},
        headers=AUTORIZACAO,
    )

    assert resposta.status_code == 201
    nova = resposta.json()
    assert (nova["nome"], nova["papel"], nova["a_revisar"]) == (
        "Zeca Pagodinho",
        "cantor",
        True,
    )
    guardada = mundo.catalogo.obter(nova["id"])
    assert guardada is not None
    assert guardada.a_revisar
    assert guardada.acrescentada_por == "ana@redetv.com.br"
    assert _nomes(mundo, URL_PESSOAS, "zeca") == ["Zeca Pagodinho"]


def test_nome_repetido_devolve_a_existente_sem_duplicar() -> None:
    mundo = _mundo_com_pessoas()
    sabrina = mundo.catalogo.achar("Sabrina Sato")[0]
    antes = len(mundo.catalogo.todas())

    for nome in ("sabrina sato", "SABRININHA", "Sabrina  Sato"):
        resposta = mundo.cliente.post(
            URL_PESSOAS, json={"nome": nome}, headers=AUTORIZACAO
        )

        assert resposta.status_code == 200
        assert resposta.json()["id"] == sabrina.id
        assert resposta.json()["a_revisar"] is False

    assert len(mundo.catalogo.todas()) == antes


def test_o_nome_novo_repetido_duas_vezes_entra_uma_vez() -> None:
    mundo = Mundo(["editor"])

    primeira = mundo.cliente.post(
        URL_PESSOAS, json={"nome": "Nova"}, headers=AUTORIZACAO
    )
    segunda = mundo.cliente.post(
        URL_PESSOAS, json={"nome": "nova"}, headers=AUTORIZACAO
    )

    assert (primeira.status_code, segunda.status_code) == (201, 200)
    assert primeira.json()["id"] == segunda.json()["id"]
    assert primeira.json()["rotulo"] == "Nova"  # sem papel, sem parênteses
    assert len(mundo.catalogo.todas()) == 1


def test_so_quem_edita_acrescenta() -> None:
    mundo = Mundo(["consulta"])

    resposta = mundo.cliente.post(URL_PESSOAS, json={"nome": "X"}, headers=AUTORIZACAO)

    assert resposta.status_code == 403
    assert mundo.catalogo.todas() == []


@pytest.mark.parametrize(
    "corpo",
    [{"nome": ""}, {"nome": "   "}, {"nome": "a" * 201}, {"nome": "x\x00y"}, {}],
)
def test_nome_invalido_nao_entra(corpo: dict[str, Any]) -> None:
    mundo = Mundo(["editor"])

    resposta = mundo.cliente.post(URL_PESSOAS, json=corpo, headers=AUTORIZACAO)

    assert resposta.status_code == 422
    assert mundo.catalogo.todas() == []


def test_marcas_por_prefixo_apelido_acento_e_limite() -> None:
    mundo = Mundo(["editor"])
    mundo.marcas.acrescentar("Banco Verde", ["BV"])
    mundo.marcas.acrescentar("Café Pelé", [])
    for i in range(12):
        mundo.marcas.acrescentar(f"Loja {i:02d}", [])

    assert _nomes(mundo, URL_MARCAS, "banc") == ["Banco Verde"]
    assert _nomes(mundo, URL_MARCAS, "bv") == ["Banco Verde"]
    assert _nomes(mundo, URL_MARCAS, "CAFE") == ["Café Pelé"]
    assert _nomes(mundo, URL_MARCAS, "verd") == ["Banco Verde"]
    assert _nomes(mundo, URL_MARCAS, "bancp") == ["Banco Verde"]  # erro de digitação
    assert len(_nomes(mundo, URL_MARCAS, "loj")) == 10


def test_marca_nova_entra_a_revisar_e_repetida_nao_duplica() -> None:
    mundo = Mundo(["editor"])
    existente = mundo.marcas.acrescentar("Banco Verde", [])

    nova = mundo.cliente.post(
        URL_MARCAS, json={"nome": "Loja Sol"}, headers=AUTORIZACAO
    )
    repetida = mundo.cliente.post(
        URL_MARCAS, json={"nome": "banco verde"}, headers=AUTORIZACAO
    )

    assert nova.status_code == 201
    assert nova.json()["a_revisar"] is True
    guardada = mundo.marcas.obter(nova.json()["id"])
    assert guardada is not None
    assert guardada.acrescentada_por == "ana@redetv.com.br"
    assert (repetida.status_code, repetida.json()["id"]) == (200, existente.id)
    assert len(mundo.marcas.todas()) == 2
    assert _nomes(mundo, URL_MARCAS, "loja") == ["Loja Sol"]


def test_so_quem_edita_acrescenta_marca() -> None:
    mundo = Mundo(["consulta"])

    resposta = mundo.cliente.post(URL_MARCAS, json={"nome": "X"}, headers=AUTORIZACAO)

    assert resposta.status_code == 403
    assert mundo.marcas.todas() == []
