"""#484: o autocompletar acha o mesmo de antes e normaliza os nomes uma vez por cópia."""

import random

import pytest

from api import achar_nomes
from api.achar_nomes import LIMITE_DO_AUTOCOMPLETAR, IndiceDeNomes, achar_por_prefixo
from api.comparador import normalizar


class _Item:
    def __init__(self, nome: str, apelidos: list[str]) -> None:
        self.nome, self.apelidos = nome, apelidos


def _antigo(
    itens: list[_Item], consulta: str, limite: int = LIMITE_DO_AUTOCOMPLETAR
) -> list[_Item]:
    """A implementação de antes do #484: normaliza cada nome a cada pedido."""
    termos = normalizar(consulta).split()
    if not termos:
        return []
    achados = []
    for item in itens:
        custos = [
            c
            for nome in (item.nome, *item.apelidos)
            if (c := achar_nomes._custo_no_nome(termos, normalizar(nome))) is not None
        ]
        if custos:
            achados.append((min(custos), normalizar(item.nome), item))
    achados.sort(key=lambda a: (a[0], a[1]))
    return [item for _, _, item in achados[:limite]]


def _catalogo() -> list[_Item]:
    sorteio = random.Random(484)
    silabas = [
        "sa",
        "bri",
        "na",
        "sa",
        "to",
        "Ângela",
        "Ça",
        "mar",
        "ia",
        "José",
        "lu",
        "ana",
    ]
    itens = []
    for _ in range(150):
        nome = " ".join(
            "".join(sorteio.choices(silabas, k=2)) for _ in range(sorteio.randint(1, 3))
        )
        apelidos = [
            "".join(sorteio.choices(silabas, k=2)) for _ in range(sorteio.randint(0, 2))
        ]
        itens.append(_Item(nome, apelidos))
    return itens


@pytest.mark.parametrize(
    "consulta",
    [
        "sa",
        "SABRI",
        "sabrina",
        "angela",
        "jose lu",
        "marai",
        "saba to",
        "zzz",
        " ",
        "çana",
        "anaa",
    ],
)
def test_mesmo_resultado_da_implementacao_anterior(consulta: str) -> None:
    itens = _catalogo()
    indice = IndiceDeNomes[_Item]()
    esperado = _antigo(itens, consulta)
    assert achar_por_prefixo(itens, consulta) == esperado
    assert achar_por_prefixo(indice.de(itens), consulta) == esperado


def test_completa_com_aproximados_depois_dos_exatos_e_limita_a_dez() -> None:
    itens = [_Item(f"Mariana {i:02}", []) for i in range(8)] + [
        _Item(f"Marina {i}", []) for i in range(8)
    ]
    achados = achar_por_prefixo(IndiceDeNomes[_Item]().de(itens), "mariana")
    assert len(achados) == LIMITE_DO_AUTOCOMPLETAR
    assert [i.nome for i in achados[:8]] == [f"Mariana {i:02}" for i in range(8)]
    assert all(i.nome.startswith("Marina") for i in achados[8:])


def test_normaliza_cada_nome_uma_vez_por_copia(monkeypatch: pytest.MonkeyPatch) -> None:
    itens = _catalogo()
    chamadas: list[str] = []

    def contando(texto: str) -> str:
        chamadas.append(texto)
        return normalizar(texto)

    monkeypatch.setattr(achar_nomes, "normalizar", contando)
    indice = IndiceDeNomes[_Item]()
    achar_por_prefixo(indice.de(itens), "sa")
    depois_da_carga = len(chamadas)
    for consulta in ("sab", "sabr", "jose"):
        achar_por_prefixo(indice.de(itens), consulta)
    # Só a consulta é normalizada a cada pedido, nunca os nomes.
    assert len(chamadas) == depois_da_carga + 3


def test_copia_nova_refaz_o_indice() -> None:
    indice = IndiceDeNomes[_Item]()
    antes = [_Item("Ana Souza", [])]
    assert [i.nome for i in achar_por_prefixo(indice.de(antes), "ana")] == ["Ana Souza"]
    depois = [_Item("Beatriz", [])]
    assert achar_por_prefixo(indice.de(depois), "ana") == []
