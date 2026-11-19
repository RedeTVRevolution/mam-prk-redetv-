from api.variantes import Variantes


def test_grafias_que_so_mudam_na_escrita_sao_o_mesmo_nome() -> None:
    v = Variantes(["Lordello", "lordelo", "Thiago", "Tiago", "Rayane", "Raiane"])
    assert v.de("lordelo") == {"lordello"}
    assert v.de("Lordello") == {"lordelo"}
    assert v.de("tiago") == {"thiago"}
    assert v.de("raiane") == {"rayane"}


def test_vogal_diferente_e_outro_nome() -> None:
    assert Variantes(["Bruno", "Bruna"]).de("bruno") == set()


def test_palavra_fora_da_lista_nao_ganha_variante() -> None:
    # "caro" casaria com "carro" pela chave, mas só os nomes da lista têm variante.
    assert Variantes(["Carro"]).de("caro") == set()
    assert Variantes([]).de("carro") == set()
