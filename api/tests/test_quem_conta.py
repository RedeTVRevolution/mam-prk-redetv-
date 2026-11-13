"""Quem conta (#610): a pergunta única que a leitura faz ao catálogo depois da lixeira, da
purga e da fusão. Os testes passam só pela interface do módulo, com catálogo, marcas e
purgas em memória."""

import ast
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from google.api_core.exceptions import ServiceUnavailable

import api.quem_conta
from api.catalogo import (
    CatalogoEmMemoria,
    EnvioParaLixeira,
    FusaoDaPessoa,
    PessoaDoCatalogo,
)
from api.erros import ServicoIndisponivel
from api.lixeira_na_leitura import PurgasDeMarcaEmMemoria
from api.marcas import CatalogoDeMarcasEmMemoria, MarcaDoCatalogo
from api.quem_conta import QuemConta

BASE = datetime(2026, 11, 1, tzinfo=UTC)
ENVIO = EnvioParaLixeira(em=BASE, por_uid="u", por_email="u@redetv.com", motivo="teste")


def _fusao(destino: PessoaDoCatalogo) -> FusaoDaPessoa:
    return FusaoDaPessoa(
        destino_id=destino.id,
        em=BASE,
        por_uid="u",
        por_email="u@redetv.com",
        motivo="duplicada",
    )


def _dias(n: int) -> datetime:
    return BASE + timedelta(days=n)


class CatalogoQueConta(CatalogoEmMemoria):
    """Anota cada id pedido em lote, para provar que um id é lido uma vez por operação."""

    def __init__(self) -> None:
        super().__init__()
        self.lidos: list[str] = []

    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]:
        ids = list(ids)
        self.lidos.extend(ids)
        return super().obter_varios(ids)


class MarcasQueContam(CatalogoDeMarcasEmMemoria):
    def __init__(self) -> None:
        super().__init__()
        self.lidos: list[str] = []
        self.leituras_da_lixeira = 0

    def obter_varios(self, ids: Iterable[str]) -> dict[str, MarcaDoCatalogo]:
        ids = list(ids)
        self.lidos.extend(ids)
        return super().obter_varios(ids)

    def na_lixeira(self) -> list[MarcaDoCatalogo]:
        self.leituras_da_lixeira += 1
        return super().na_lixeira()


def _cai(*_: Any) -> Any:
    raise ServiceUnavailable("firestore fora")  # type: ignore[no-untyped-call]


# --- pessoas -------------------------------------------------------------------------


def test_pessoas_conta_quem_tem_registro_fora_da_lixeira() -> None:
    catalogo = CatalogoEmMemoria()
    ana = catalogo.acrescentar("Ana", "", [])
    bia = catalogo.acrescentar("Bia", "", [])
    cris = catalogo.acrescentar("Cris", "", [])
    catalogo.definir_lixeira(bia.id, ENVIO)
    catalogo.apagar(cris.id)

    destinos = QuemConta(catalogo, None, PurgasDeMarcaEmMemoria()).pessoas(
        [ana.id, bia.id, cris.id, "nunca-existiu"]
    )

    assert {i: d.conta for i, d in destinos.items()} == {
        ana.id: True,
        bia.id: False,
        cris.id: False,
        "nunca-existiu": False,
    }
    assert destinos[ana.id].pessoa == ana
    assert not destinos[ana.id].fundida
    # Na lixeira o registro existe (para quem o esconde e o guarda); purgada, não.
    assert destinos[bia.id].pessoa is not None
    assert destinos[cris.id].pessoa is None


def test_a_fundida_resolve_o_registro_no_fim_da_cadeia() -> None:
    catalogo = CatalogoEmMemoria()
    a, b, c = (catalogo.acrescentar(n, "", []) for n in "ABC")
    catalogo.definir_fusao(a.id, _fusao(b))
    catalogo.definir_fusao(b.id, _fusao(c))

    destinos = QuemConta(catalogo, None, PurgasDeMarcaEmMemoria()).pessoas(
        [a.id, b.id, c.id]
    )

    assert [(d.pessoa.id, d.fundida) for d in destinos.values() if d.pessoa] == [
        (c.id, True),
        (c.id, True),
        (c.id, False),
    ]
    assert all(d.conta for d in destinos.values())


def test_destino_da_fusao_na_lixeira_ou_purgado_tira_a_origem() -> None:
    catalogo = CatalogoEmMemoria()
    a, b = (catalogo.acrescentar(n, "", []) for n in "AB")
    catalogo.definir_fusao(a.id, _fusao(b))

    catalogo.definir_lixeira(b.id, ENVIO)
    na_lixeira = QuemConta(catalogo, None, PurgasDeMarcaEmMemoria()).pessoas([a.id])
    assert not na_lixeira[a.id].conta
    assert na_lixeira[a.id].pessoa == catalogo.obter(b.id)  # o registro do destino
    assert na_lixeira[a.id].fundida

    catalogo.apagar(b.id)
    purgado = QuemConta(catalogo, None, PurgasDeMarcaEmMemoria()).pessoas([a.id])
    assert purgado[a.id].pessoa is None
    assert not purgado[a.id].conta


def test_origem_na_lixeira_nao_conta_mesmo_com_o_destino_valendo() -> None:
    catalogo = CatalogoEmMemoria()
    a, b = (catalogo.acrescentar(n, "", []) for n in "AB")
    catalogo.definir_fusao(a.id, _fusao(b))
    catalogo.definir_lixeira(a.id, ENVIO)

    quem = QuemConta(catalogo, None, PurgasDeMarcaEmMemoria())

    assert quem.contam([a.id, b.id]) == {b.id}


def test_ciclo_de_fusao_nao_prende_e_e_tratado_como_purgado() -> None:
    catalogo = CatalogoEmMemoria()
    a, b, c, d = (catalogo.acrescentar(n, "", []) for n in "ABCD")
    catalogo.definir_fusao(a.id, _fusao(b))  # A→B→C→D→B
    catalogo.definir_fusao(b.id, _fusao(c))
    catalogo.definir_fusao(c.id, _fusao(d))
    catalogo.definir_fusao(d.id, _fusao(b))

    destinos = QuemConta(catalogo, None, PurgasDeMarcaEmMemoria()).pessoas(
        [a.id, b.id, c.id, d.id]
    )

    assert all(d.pessoa is None and not d.conta for d in destinos.values())


def test_cadeia_valida_de_qualquer_tamanho_conta() -> None:
    catalogo = CatalogoEmMemoria()
    elos = [catalogo.acrescentar(f"P{i}", "", []) for i in range(13)]
    for de, para in pairwise(elos):
        catalogo.definir_fusao(de.id, _fusao(para))

    assert QuemConta(catalogo, None, PurgasDeMarcaEmMemoria()).contam([elos[0].id]) == {
        elos[0].id
    }


def test_sem_catalogo_de_pessoas_ninguem_e_filtrado() -> None:
    quem = QuemConta(None, None, PurgasDeMarcaEmMemoria())

    assert quem.contam(["a", "b"]) == {"a", "b"}


def test_cada_id_e_lido_uma_vez_na_operacao_inclusive_ausencias_e_elos() -> None:
    catalogo = CatalogoQueConta()
    a, b, c = (catalogo.acrescentar(n, "", []) for n in "ABC")
    catalogo.definir_fusao(a.id, _fusao(c))
    catalogo.definir_fusao(b.id, _fusao(c))
    catalogo.lidos.clear()
    quem = QuemConta(catalogo, None, PurgasDeMarcaEmMemoria())

    quem.pessoas([a.id, b.id, "sumida"])
    quem.pessoas([c.id, a.id, "sumida"])
    quem.contam([a.id, b.id, c.id, "sumida"])

    assert sorted(catalogo.lidos) == sorted([a.id, b.id, c.id, "sumida"])


def test_falha_do_firestore_na_leitura_do_catalogo_vira_servico_indisponivel() -> None:
    catalogo = CatalogoEmMemoria()
    catalogo.obter_varios = _cai  # type: ignore[method-assign,assignment]
    quem = QuemConta(catalogo, None, PurgasDeMarcaEmMemoria())

    with pytest.raises(ServicoIndisponivel):
        quem.pessoas(["a"])
    with pytest.raises(ServicoIndisponivel):
        quem.contam(["a"])


# --- marcas vivas ---------------------------------------------------------------------


def test_marcas_vivas_sao_as_que_existem_fora_da_lixeira() -> None:
    marcas = CatalogoDeMarcasEmMemoria()
    viva = marcas.acrescentar("Nike", [])
    lixo = marcas.acrescentar("Adidas", [])
    marcas.definir_lixeira(lixo.id, ENVIO)
    quem = QuemConta(None, marcas, PurgasDeMarcaEmMemoria())

    assert quem.marcas_vivas([viva.id, lixo.id, "sumida"]) == {viva.id}


def test_sem_catalogo_de_marcas_toda_marca_e_viva() -> None:
    quem = QuemConta(None, None, PurgasDeMarcaEmMemoria())

    assert quem.marcas_vivas(["m1", "m2"]) == {"m1", "m2"}


def test_falha_do_firestore_na_leitura_das_marcas_vira_servico_indisponivel() -> None:
    marcas = CatalogoDeMarcasEmMemoria()
    marcas.obter_varios = _cai  # type: ignore[method-assign,assignment]
    quem = QuemConta(None, marcas, PurgasDeMarcaEmMemoria())

    with pytest.raises(ServicoIndisponivel):
        quem.marcas_vivas(["m1"])


# --- cortes ---------------------------------------------------------------------------


def _purgada(
    marcas: CatalogoDeMarcasEmMemoria,
    purgas: PurgasDeMarcaEmMemoria,
    nome: str,
    apelidos: list[str],
    em: datetime,
) -> None:
    marca = marcas.acrescentar(nome, apelidos)
    purgas.gravar(marca, em)
    marcas.apagar(marca.id)


def test_corte_vale_o_da_purga_mais_recente_e_um_job_ausente_conta_como_anterior() -> (
    None
):
    marcas, purgas = CatalogoDeMarcasEmMemoria(), PurgasDeMarcaEmMemoria()
    _purgada(marcas, purgas, "Nike", [], _dias(1))
    _purgada(marcas, purgas, "Nike", [], _dias(3))

    cortes = QuemConta(None, marcas, purgas).cortes({"nike", "adidas"})

    assert cortes.tem_corte("nike") and not cortes.tem_corte("adidas")
    assert not cortes.conta("nike", _dias(2))
    assert cortes.conta("nike", _dias(4))
    assert not cortes.conta("nike", None)
    assert cortes.conta("adidas", None)


def test_lotes_sucessivos_nao_rebaixam_o_corte() -> None:
    marcas, purgas = CatalogoDeMarcasEmMemoria(), PurgasDeMarcaEmMemoria()
    _purgada(marcas, purgas, "Nike", ["Swoosh"], _dias(1))  # {nike, swoosh}
    _purgada(marcas, purgas, "Swoosh", [], _dias(3))  # {swoosh}
    quem = QuemConta(None, marcas, purgas)

    primeiro = quem.cortes({"swoosh"})
    segundo = quem.cortes({"nike"})  # a purga de Nike também cita swoosh
    de_novo = quem.cortes({"swoosh", "nike"})

    assert not primeiro.conta("swoosh", _dias(2))
    assert not segundo.conta("nike", _dias(0))
    assert segundo.conta("nike", _dias(2))  # só a purga de Nike, em D1
    assert not de_novo.conta("swoosh", _dias(2))
    assert de_novo.conta("swoosh", _dias(4))


def test_marca_na_lixeira_nao_conta_pelo_nome_e_pelo_apelido() -> None:
    marcas = CatalogoDeMarcasEmMemoria()
    nike = marcas.acrescentar("Nike", ["Swoosh"])
    marcas.definir_lixeira(nike.id, ENVIO)

    cortes = QuemConta(None, marcas, PurgasDeMarcaEmMemoria()).cortes(
        {"nike", "swoosh", "adidas"}
    )

    assert not cortes.conta("nike", _dias(9))
    assert not cortes.conta("swoosh", _dias(9))
    assert cortes.conta("adidas", _dias(9))
    # A lixeira não é corte de purga: não há Job a consultar.
    assert not cortes.tem_corte("nike")


def test_so_com_a_purga_a_lixeira_nao_conta() -> None:
    marcas, purgas = CatalogoDeMarcasEmMemoria(), PurgasDeMarcaEmMemoria()
    nike = marcas.acrescentar("Nike", [])
    marcas.definir_lixeira(nike.id, ENVIO)
    _purgada(marcas, purgas, "Adidas", [], _dias(1))

    cortes = QuemConta(None, marcas, purgas).cortes({"nike", "adidas"}, so_a_purga=True)

    assert cortes.conta("nike", None)
    assert not cortes.conta("adidas", _dias(0))


def test_purga_cuja_marca_ainda_existe_nao_corta() -> None:
    marcas, purgas = CatalogoDeMarcasEmMemoria(), PurgasDeMarcaEmMemoria()
    nike = marcas.acrescentar("Nike", [])
    purgas.gravar(nike, _dias(1))  # gravou o registro, o apagar falhou

    cortes = QuemConta(None, marcas, purgas).cortes({"nike"})

    assert cortes.conta("nike", _dias(0))
    assert not cortes.tem_corte("nike")


def test_sem_catalogo_de_marcas_nada_e_cortado() -> None:
    marcas, purgas = CatalogoDeMarcasEmMemoria(), PurgasDeMarcaEmMemoria()
    _purgada(marcas, purgas, "Nike", [], _dias(1))

    cortes = QuemConta(None, None, purgas).cortes({"nike"})

    assert cortes.conta("nike", None)


def test_as_marcas_e_as_purgas_sao_lidas_uma_vez_na_operacao() -> None:
    marcas, purgas = MarcasQueContam(), PurgasDeMarcaEmMemoria()
    marca = marcas.acrescentar("Nike", [])
    purgas.gravar(marca, _dias(1))
    marcas.apagar(marca.id)
    quem = QuemConta(None, marcas, purgas)

    quem.cortes({"nike"})
    quem.cortes({"nike", "adidas"})
    quem.cortes({"adidas"})

    assert marcas.leituras_da_lixeira == 1
    assert marcas.lidos == [marca.id]


@pytest.mark.parametrize("que_cai", ["na_lixeira", "purgas", "marcas"])
def test_falha_do_firestore_nos_cortes_vira_servico_indisponivel(que_cai: str) -> None:
    marcas, purgas = CatalogoDeMarcasEmMemoria(), PurgasDeMarcaEmMemoria()
    _purgada(marcas, purgas, "Nike", [], _dias(1))
    if que_cai == "na_lixeira":
        marcas.na_lixeira = _cai  # type: ignore[method-assign]
    elif que_cai == "purgas":
        purgas.todas = _cai  # type: ignore[method-assign]
    else:
        marcas.obter_varios = _cai  # type: ignore[method-assign,assignment]
    quem = QuemConta(None, marcas, purgas)

    with pytest.raises(ServicoIndisponivel):
        quem.cortes({"nike"})


def test_so_com_a_purga_a_lixeira_das_marcas_nao_e_lida() -> None:
    marcas = MarcasQueContam()
    marcas.na_lixeira = _cai  # type: ignore[method-assign]

    QuemConta(None, marcas, PurgasDeMarcaEmMemoria()).cortes({"nike"}, so_a_purga=True)


# --- fronteira ------------------------------------------------------------------------


def test_quem_conta_nao_importa_o_modulo_de_jobs() -> None:
    importados: set[str] = set()
    for no in ast.walk(ast.parse(Path(api.quem_conta.__file__).read_text())):
        if isinstance(no, ast.Import):
            importados |= {a.name for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            importados.add(no.module)
            importados |= {f"{no.module}.{a.name}" for a in no.names}

    assert "api.jobs" not in importados
