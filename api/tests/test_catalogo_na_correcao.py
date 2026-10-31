"""A correção de nome da revisora grava o `catalogo_id` da pessoa do catálogo
que casa com o nome novo (#108)."""

from api.tests.test_correcoes import MODELO, Mundo
from api.tests.test_correcoes import _pessoa as _pessoa_do_modelo


def _pessoa(mundo: Mundo, id: str) -> dict[str, object]:
    return next(p for p in mundo.decupagem()["pessoas"] if p["id"] == id)


def test_nome_que_casa_com_o_catalogo_grava_o_id_da_pessoa() -> None:
    mundo = Mundo(["editor"])
    ana = mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])

    assert mundo.corrigir().status_code == 201

    assert _pessoa(mundo, "pes01")["catalogo_id"] == ana.id
    assert mundo.historico().json()[0]["catalogo_id"] == ana.id


def test_casa_pelo_apelido_e_sem_diferenca_de_acento() -> None:
    mundo = Mundo(["editor"])
    ana = mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", ["Aninha"])

    mundo.corrigir(valor="ANINHA")

    assert _pessoa(mundo, "pes01")["catalogo_id"] == ana.id


def test_nome_que_nao_casa_deixa_o_campo_vazio() -> None:
    mundo = Mundo(["editor"])
    mundo.catalogo.acrescentar("Outra Pessoa", "repórter", [])

    assert mundo.corrigir().status_code == 201

    assert _pessoa(mundo, "pes01").get("catalogo_id") is None


def test_nome_que_casa_com_duas_pessoas_do_catalogo_nao_escolhe() -> None:
    mundo = Mundo(["editor"])
    mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])
    mundo.catalogo.acrescentar("Ana Souza Lima", "atriz", [])

    mundo.corrigir()

    assert _pessoa(mundo, "pes01").get("catalogo_id") is None


def test_correcao_desfeita_nao_deixa_o_catalogo_id() -> None:
    mundo = Mundo(["editor"])
    mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])
    cid = mundo.corrigir().json()["id"]

    mundo.avancar()
    mundo.desfazer(cid)

    assert _pessoa(mundo, "pes01").get("catalogo_id") is None


def test_renomear_para_nome_fora_do_catalogo_tira_o_id_do_nome_anterior() -> None:
    mundo = Mundo(["editor"])
    mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])
    mundo.corrigir()

    mundo.avancar()
    mundo.corrigir(valor="Fulano de Tal")

    assert _pessoa(mundo, "pes01").get("catalogo_id") is None


def test_correcao_atendida_pelo_modelo_novo_mantem_o_catalogo_id() -> None:
    mundo = Mundo(["editor"])
    ana = mundo.catalogo.acrescentar("Ana Souza Lima", "repórter", [])
    mundo.corrigir()

    mundo.reprocessar(
        {**MODELO, "pessoas": [_pessoa_do_modelo("p9", "ANA SOUZA LIMA", 1200, 4800)]}
    )

    pessoa = mundo.decupagem()["pessoas"][0]
    assert (pessoa["origem"], pessoa["catalogo_id"]) == ("modelo", ana.id)
