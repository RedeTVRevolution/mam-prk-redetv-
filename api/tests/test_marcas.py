"""Catálogo de marcas (#150): o dublê e a carga inicial."""

from datetime import UTC, datetime
from typing import Any

from api.catalogo import EnvioParaLixeira
from api.marcas import (
    CatalogoDeMarcasEmMemoria,
    MarcaDoCatalogo,
    MarcasCanonicas,
    carregar_marcas,
)


def test_acrescentar_gera_id_estavel_e_achar_por_nome_ou_apelido() -> None:
    catalogo = CatalogoDeMarcasEmMemoria()

    marca = catalogo.acrescentar("Café Pelé", ["Pelé"], a_revisar=True, autor="a@b")

    assert catalogo.obter(marca.id) == marca
    assert (marca.a_revisar, marca.acrescentada_por) == (True, "a@b")
    assert catalogo.achar("CAFE pele") == [marca]
    assert catalogo.achar("pele") == [marca]
    assert catalogo.achar("outra") == []
    assert catalogo.obter("inexistente") is None
    assert catalogo.todas() == [marca]


def _decupagem(*marcas: str) -> dict[str, Any]:
    return {"comerciais": [{"marca": m, "tipo": "intervalo"} for m in marcas]}


def test_carga_acrescenta_as_marcas_dos_comerciais_sem_repetir() -> None:
    catalogo = CatalogoDeMarcasEmMemoria()

    entraram = carregar_marcas(
        catalogo,
        [
            _decupagem("Banco Verde", "Refri Cola"),
            _decupagem("banco  verde", "Refri Cola", " "),
            {"pessoas": []},  # decupagem sem comerciais
        ],
    )

    assert entraram == 2
    assert sorted(m.nome for m in catalogo.todas()) == ["Banco Verde", "Refri Cola"]
    assert not any(m.a_revisar for m in catalogo.todas())


def test_a_carga_e_idempotente() -> None:
    catalogo = CatalogoDeMarcasEmMemoria()
    decupagens = [_decupagem("Banco Verde"), _decupagem("Loja Sol")]

    primeira = carregar_marcas(catalogo, decupagens)
    ids = {m.id for m in catalogo.todas()}
    segunda = carregar_marcas(catalogo, decupagens)

    assert (primeira, segunda) == (2, 0)
    assert {m.id for m in catalogo.todas()} == ids


def test_a_carga_respeita_o_que_ja_esta_no_catalogo_por_apelido() -> None:
    catalogo = CatalogoDeMarcasEmMemoria()
    catalogo.acrescentar("Banco Verde", ["BV"])

    assert carregar_marcas(catalogo, [_decupagem("BV")]) == 0


def test_a_carga_nao_recria_marca_na_lixeira_e_recria_depois_da_purga() -> None:
    catalogo = CatalogoDeMarcasEmMemoria()
    banco = catalogo.acrescentar("Banco Verde", ["BV"])
    envio = EnvioParaLixeira(
        em=datetime(2026, 11, 1, tzinfo=UTC),
        por_uid="u1",
        por_email="c@redetv.com",
        motivo="duplicada",
    )
    catalogo.definir_lixeira(banco.id, envio)

    # pelo nome e pelo apelido
    assert carregar_marcas(catalogo, [_decupagem("banco VERDE", "bv")]) == 0
    assert catalogo.todas() == []
    assert catalogo.achar("bv") == []
    assert [m.id for m in catalogo.achar("bv", com_lixeira=True)] == [banco.id]

    catalogo.apagar(banco.id)

    assert carregar_marcas(catalogo, [_decupagem("Banco Verde")]) == 1
    assert [m.nome for m in catalogo.todas()] == ["Banco Verde"]


# --- a marca canônica: apelido e grafia que só difere na pontuação ---------------------


def _canonicas(*marcas: tuple[str, list[str]]) -> MarcasCanonicas:
    catalogo = CatalogoDeMarcasEmMemoria()
    for nome, apelidos in marcas:
        catalogo.acrescentar(nome, apelidos)
    return MarcasCanonicas(catalogo.todas())


def test_o_apelido_conta_como_a_marca_do_catalogo() -> None:
    canonicas = _canonicas(("UNIFAEL", ["UniAefel"]))

    rotulos = canonicas.rotulos({"UniAefel": 1, "UNIFAEL": 5, "unifael!": 1})

    assert set(rotulos.values()) == {"UNIFAEL"}
    assert canonicas.grupo("UniAefel") == canonicas.grupo("UNIFAEL")


def test_grafia_que_so_difere_na_pontuacao_e_a_mesma_marca_sem_catalogo() -> None:
    rotulos = _canonicas().rotulos(
        {"RedeTV! Go": 3, "RedeTV Go": 5, "RedeTV! GO": 1, "RedeTV Gol": 2}
    )

    assert {rotulos[g] for g in ("RedeTV! Go", "RedeTV Go", "RedeTV! GO")} == {
        "RedeTV Go"  # a mais frequente do grupo
    }
    assert rotulos["RedeTV Gol"] == "RedeTV Gol"  # sem distância de edição


def test_empate_de_grafia_vai_pela_ordem_alfabetica() -> None:
    rotulos = _canonicas().rotulos({"b-b": 2, "bb": 2, "BB": 2})

    assert set(rotulos.values()) == {"BB"}


def test_a_chave_no_nome_vence_a_do_apelido_e_depois_o_menor_id() -> None:
    catalogo = CatalogoDeMarcasEmMemoria()
    catalogo.acrescentar("Outra", ["Rede TV"])
    catalogo.acrescentar("RedeTV", [])

    canonicas = MarcasCanonicas(catalogo.todas())

    assert canonicas.rotulos({"rede tv": 1}) == {"rede tv": "RedeTV"}

    # Duas marcas com a chave no nome: vence a de menor id.
    gemeas = [
        MarcaDoCatalogo(id="b", nome="Rede-TV"),
        MarcaDoCatalogo(id="a", nome="RedeTV"),
    ]
    assert MarcasCanonicas(gemeas).rotulos({"redetv": 1}) == {"redetv": "RedeTV"}
