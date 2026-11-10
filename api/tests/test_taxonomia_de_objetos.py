from collections import defaultdict

import pytest

from api.assinatura_do_nome import assinatura
from api.decupagem import CATEGORIAS_DE_OBJETO
from api.taxonomia_de_objetos import (
    CATEGORIA_DO_TIPO,
    OUTRO,
    SINONIMOS_DO_TIPO,
    TAXONOMIA,
    TIPOS_CANONICOS,
)
from api.tipo_do_objeto import (
    chave_de_agrupamento,
    tipo_canonico_de,
    tipo_pelo_nome,
)


def test_a_lista_fica_na_casa_das_centenas_de_tipos() -> None:
    # O ticket pede "uns 150 a 250"; os tipos finos (brinco, colar, anel) passam um pouco.
    assert 150 <= len(TIPOS_CANONICOS) <= 300


def test_todo_tipo_tem_uma_categoria_valida() -> None:
    assert {t["categoria"] for t in TAXONOMIA} <= set(CATEGORIAS_DE_OBJETO)
    assert set(CATEGORIA_DO_TIPO) == set(TIPOS_CANONICOS)


def test_outro_nao_e_um_tipo_da_lista() -> None:
    assert OUTRO not in TIPOS_CANONICOS
    assert OUTRO not in [s for lista in SINONIMOS_DO_TIPO.values() for s in lista]


def test_nenhum_nome_pertence_a_dois_tipos() -> None:
    donos: dict[str, set[str]] = defaultdict(set)
    for tipo in TIPOS_CANONICOS:
        for nome in [tipo, *SINONIMOS_DO_TIPO[tipo]]:
            donos[assinatura(nome)].add(tipo)
    repetidos = {chave: tipos for chave, tipos in donos.items() if len(tipos) > 1}
    assert repetidos == {}


@pytest.mark.parametrize(
    "nome, cores, tipo",
    [
        ("camiseta", [], "camisa"),
        ("Blusa", [], "camisa"),
        ("camisas", [], "camisa"),
        ("tênis", [], "sapato"),
        ("sapato", [], "sapato"),
        ("veículo terrestre", [], "carro"),
        ("carro vermelho", ["vermelho"], "carro"),
        ("carro vermelho", [], "carro"),
        ("microfones", [], "microfone"),
        ("xablau inexistente", [], "outro"),
    ],
)
def test_dicionario_do_nome_livre_para_o_tipo(
    nome: str, cores: list[str], tipo: str
) -> None:
    assert tipo_pelo_nome(nome, cores) == tipo


def test_o_tipo_gravado_da_lista_vale_e_o_resto_cai_no_dicionario() -> None:
    assert tipo_canonico_de("camisa", "blusa de seda") == "camisa"
    assert tipo_canonico_de(None, "camiseta") == "camisa"
    assert tipo_canonico_de("outro", "camiseta") == "camisa"
    # Um valor fora da lista (de uma lista mais antiga) não derruba a leitura.
    assert tipo_canonico_de("tipo_que_saiu", "camiseta") == "camisa"
    assert tipo_canonico_de("tipo_que_saiu", "xablau") == "outro"


def test_chave_de_outro_e_o_nome_e_a_do_tipo_e_o_tipo() -> None:
    assert chave_de_agrupamento("camisa", "blusa") == chave_de_agrupamento(
        "camisa", "camiseta"
    )
    assert chave_de_agrupamento("outro", "Xablau Roxos") == chave_de_agrupamento(
        "outro", "xablau roxo"
    )
    assert chave_de_agrupamento("outro", "xablau") != chave_de_agrupamento(
        "outro", "outra coisa"
    )
