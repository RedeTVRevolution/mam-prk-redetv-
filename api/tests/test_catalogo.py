import pytest

from api.catalogo import (
    CatalogoEmMemoria,
    PessoaInexistente,
)


def test_acrescentar_gera_id_estavel_e_obter_devolve_a_pessoa() -> None:
    catalogo = CatalogoEmMemoria()

    leao = catalogo.acrescentar("Leão Lobo", "apresentador", ["Leãozinho"])

    assert leao.id
    assert catalogo.obter(leao.id) == leao
    assert leao.rostos == []
    assert catalogo.obter("inexistente") is None


def test_ids_nunca_se_repetem_nem_depois_de_apagar() -> None:
    catalogo = CatalogoEmMemoria()
    a = catalogo.acrescentar("Ana", "repórter", [])
    catalogo.apagar(a.id)
    b = catalogo.acrescentar("Ana", "repórter", [])

    assert a.id != b.id


def test_achar_por_nome_sem_diferenca_de_maiusculas_e_acentos() -> None:
    catalogo = CatalogoEmMemoria()
    andrea = catalogo.acrescentar("Andréa Corazza", "repórter", [])

    assert catalogo.achar("ANDREA corazza") == [andrea]
    assert catalogo.achar("Outra Pessoa") == []


def test_achar_por_apelido() -> None:
    catalogo = CatalogoEmMemoria()
    leao = catalogo.acrescentar("Leão Lobo", "apresentador", ["Leãozinho"])

    assert catalogo.achar("leaozinho") == [leao]


def test_corrigir_troca_nome_papel_e_apelidos_mantendo_o_id() -> None:
    catalogo = CatalogoEmMemoria()
    p = catalogo.acrescentar("Leao Lobo", "comentarista", [])

    nova = catalogo.corrigir(
        p.id, nome="Leão Lobo", papel="apresentador", apelidos=["Leãozinho"]
    )

    assert nova.id == p.id
    assert (nova.nome, nova.papel, nova.apelidos) == (
        "Leão Lobo",
        "apresentador",
        ["Leãozinho"],
    )
    assert catalogo.obter(p.id) == nova
    assert catalogo.achar("leaozinho") == [nova]


def test_corrigir_so_o_que_foi_pedido() -> None:
    catalogo = CatalogoEmMemoria()
    p = catalogo.acrescentar("Ana", "repórter", ["Aninha"])

    nova = catalogo.corrigir(p.id, papel="apresentadora")

    assert (nova.nome, nova.papel, nova.apelidos) == (
        "Ana",
        "apresentadora",
        ["Aninha"],
    )


def test_corrigir_e_apagar_pessoa_inexistente() -> None:
    catalogo = CatalogoEmMemoria()

    with pytest.raises(PessoaInexistente):
        catalogo.corrigir("x", nome="Ana")
    with pytest.raises(PessoaInexistente):
        catalogo.apagar("x")


def test_apagar_tira_a_pessoa_da_busca() -> None:
    catalogo = CatalogoEmMemoria()
    p = catalogo.acrescentar("Ana", "repórter", ["Aninha"])

    catalogo.apagar(p.id)

    assert catalogo.obter(p.id) is None
    assert catalogo.achar("Ana") == []
    assert catalogo.achar("Aninha") == []
