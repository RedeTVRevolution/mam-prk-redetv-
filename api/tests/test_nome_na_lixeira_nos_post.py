"""O nome que já existe, na lixeira ou fora dela, não cria outro registro (#715)."""

from datetime import UTC, datetime
from typing import cast

import pytest

from api.catalogo import CatalogoEmMemoria, EnvioParaLixeira
from api.tests.test_correcoes import AUTORIZACAO, Mundo
from api.tests.test_programas import AUTORIZACAO as AUTORIZACAO_PROGRAMAS
from api.tests.test_programas import _cliente

BASE = datetime(2026, 11, 4, tzinfo=UTC)
ENVIO = EnvioParaLixeira(em=BASE, por_uid="u1", por_email="c@redetv.com", motivo="x")
LIXEIRA = "está na lixeira e pode ser restaurado"


def test_pessoa_e_marca_na_lixeira_respondem_409_sem_criar() -> None:
    mundo = Mundo(["editor"])
    pessoa = mundo.catalogo.acrescentar("Ana Lima", "repórter", [])
    marca = mundo.marcas.acrescentar("Marca X", [])
    mundo.catalogo.definir_lixeira(pessoa.id, ENVIO)
    mundo.marcas.definir_lixeira(marca.id, ENVIO)

    p = mundo.cliente.post(
        "/v1/catalogo/pessoas",
        json={"nome": "ana lima", "papel": "x"},
        headers=AUTORIZACAO,
    )
    m = mundo.cliente.post(
        "/v1/catalogo/marcas", json={"nome": "MARCA x"}, headers=AUTORIZACAO
    )

    assert (p.status_code, m.status_code) == (409, 409)
    assert LIXEIRA in p.json()["detail"] and LIXEIRA in m.json()["detail"]
    assert len(mundo.catalogo._itens) == 1 and len(mundo.marcas._itens) == 1


def test_nome_fora_da_lixeira_devolve_o_existente_com_200() -> None:
    mundo = Mundo(["editor"])
    pessoa = mundo.catalogo.acrescentar("Ana Lima", "repórter", [])
    marca = mundo.marcas.acrescentar("Marca X", [])

    p = mundo.cliente.post(
        "/v1/catalogo/pessoas",
        json={"nome": "Ana Lima", "papel": "x"},
        headers=AUTORIZACAO,
    )
    m = mundo.cliente.post(
        "/v1/catalogo/marcas", json={"nome": "Marca X"}, headers=AUTORIZACAO
    )

    assert (p.status_code, m.status_code) == (200, 200)
    assert (p.json()["id"], m.json()["id"]) == (pessoa.id, marca.id)
    assert len(mundo.catalogo._itens) == 1 and len(mundo.marcas._itens) == 1


@pytest.mark.parametrize("primeiro_na_lixeira", [True, False])
def test_homonimo_ativo_vale_sobre_o_da_lixeira(primeiro_na_lixeira: bool) -> None:
    mundo = Mundo(["editor"])
    p1 = mundo.catalogo.acrescentar("Ana Lima", "repórter", [])
    p2 = mundo.catalogo.acrescentar("Ana Lima", "repórter", [])
    m1 = mundo.marcas.acrescentar("Marca X", [])
    m2 = mundo.marcas.acrescentar("Marca X", [])
    lixo_p, ativa_p = (p1, p2) if primeiro_na_lixeira else (p2, p1)
    lixo_m, ativa_m = (m1, m2) if primeiro_na_lixeira else (m2, m1)
    mundo.catalogo.definir_lixeira(lixo_p.id, ENVIO)
    mundo.marcas.definir_lixeira(lixo_m.id, ENVIO)

    p = mundo.cliente.post(
        "/v1/catalogo/pessoas",
        json={"nome": "Ana Lima", "papel": "x"},
        headers=AUTORIZACAO,
    )
    m = mundo.cliente.post(
        "/v1/catalogo/marcas", json={"nome": "Marca X"}, headers=AUTORIZACAO
    )

    assert (p.status_code, m.status_code) == (200, 200)
    assert (p.json()["id"], m.json()["id"]) == (ativa_p.id, ativa_m.id)


def test_pessoa_do_programa_na_lixeira_409_existente_200_nova_201() -> None:
    cliente, _, c = _cliente(["editor"])
    catalogo = cast(CatalogoEmMemoria, c)
    antes = len(catalogo._itens)
    existente = catalogo.acrescentar("Ana Lima", "", [])
    na_lixeira = catalogo.acrescentar("Bia Souza", "", [])
    catalogo.definir_lixeira(na_lixeira.id, ENVIO)
    url = "/v1/admin/programas/pessoas"

    lixo = cliente.post(url, json={"nome": "Bia Souza"}, headers=AUTORIZACAO_PROGRAMAS)
    de_novo = cliente.post(
        url, json={"nome": "Ana Lima"}, headers=AUTORIZACAO_PROGRAMAS
    )
    nova = cliente.post(url, json={"nome": "Cris Nova"}, headers=AUTORIZACAO_PROGRAMAS)

    assert lixo.status_code == 409 and LIXEIRA in lixo.json()["detail"]
    assert (de_novo.status_code, de_novo.json()["pessoa_id"]) == (200, existente.id)
    assert nova.status_code == 201
    assert len(catalogo._itens) == antes + 3


@pytest.mark.parametrize("com_lixeira", [False, True])
def test_achar_de_pessoa_esconde_a_lixeira_so_por_padrao(com_lixeira: bool) -> None:
    catalogo = CatalogoEmMemoria()
    pessoa = catalogo.acrescentar("Ana Lima", "", [])
    catalogo.definir_lixeira(pessoa.id, ENVIO)

    achadas = catalogo.achar("ana lima", com_lixeira=com_lixeira)

    assert [p.id for p in achadas] == ([pessoa.id] if com_lixeira else [])
