"""O pareamento sem custo quadrático (#657): mesma saída de antes, tempo que não explode.

O oráculo é o `parear` e o `_um_para_um` de antes da mudança, copiados aqui.
"""

import random
import time
from collections.abc import Iterable

import pytest

from api.comparacao_de_passadas import _um_para_um
from api.pareamento import (
    TIPOS,
    TIPOS_COM_IDENTIDADE,
    Item,
    Pareado,
    Tipo,
    parear,
    se_sobrepoem,
    sobreposicao_ms,
)
from api.texto import normalizar


def parear_de_antes(
    gabarito: Iterable[Item], modelo: list[Item]
) -> tuple[list[Pareado], list[Item]]:
    pareados: list[Pareado] = []
    sem_par: list[Item] = []
    for g in gabarito:
        candidatos = [
            m
            for m in modelo
            if m.tipo == g.tipo
            and (
                g.tipo not in TIPOS_COM_IDENTIDADE
                or normalizar(m.identidade) == normalizar(g.identidade)
            )
            and se_sobrepoem(g, m)
        ]
        if not candidatos:
            sem_par.append(g)
            continue
        melhor = max(
            candidatos,
            key=lambda m: (
                sobreposicao_ms(g, m),
                -(abs(m.inicio_ms - g.inicio_ms) + abs(m.fim_ms - g.fim_ms)),
            ),
        )
        pareados.append(Pareado(g, melhor))
    return pareados, sem_par


def um_para_um_de_antes(
    pareados: list[Pareado], b: list[Item]
) -> tuple[list[Pareado], list[Item], list[Item]]:
    sobra_b = list(b)
    pares: list[Pareado] = []
    repetidos: list[Item] = []
    for p in pareados:
        if p.modelo in sobra_b:
            sobra_b.remove(p.modelo)
            pares.append(p)
        else:
            repetidos.append(p.gabarito)
    return pares, repetidos, sobra_b


_NOMES = ["Ana", "ANA", "Ána", "  ana  ", "José", "Jose", "JOSÉ", "Lu", "Zé", "x", "y"]


def _itens(
    rng: random.Random, quantos: int, tipos: tuple[Tipo, ...] = TIPOS, passo: int = 500
) -> list[Item]:
    itens: list[Item] = []
    for i in range(quantos):
        inicio = i * passo + rng.randrange(-300, 301)
        duracao = rng.choice([0, 0, 2000, 3000, 5000, 9000, 40_000])
        itens.append(
            Item(
                rng.choice(tipos),
                rng.choice(_NOMES[:7]),
                max(0, inicio),
                max(0, inicio) + duracao,
            )
        )
    return itens


def _dois_lados(
    semente: int, quantos: int, tipos: tuple[Tipo, ...] = TIPOS
) -> tuple[list[Item], list[Item]]:
    rng = random.Random(semente)
    a = _itens(rng, quantos, tipos)
    # o outro lado: os mesmos deslocados, com sobra, repetidos e fora de ordem
    b = [
        Item(
            i.tipo,
            rng.choice([i.identidade, i.identidade.upper()]),
            max(0, i.inicio_ms + rng.randrange(-300, 301)),
            max(0, i.fim_ms + rng.randrange(-300, 301)),
        )
        for i in a
        if rng.random() < 0.9
    ]
    b += _itens(rng, quantos // 5, tipos)
    b += rng.sample(b, len(b) // 10)  # itens iguais repetidos
    b += [
        Item(i.tipo, i.identidade, i.inicio_ms, i.fim_ms)
        for i in a[:: max(1, quantos // 7)]
    ]
    rng.shuffle(b)
    rng.shuffle(a)
    return a, b


@pytest.mark.parametrize("semente", range(24))
@pytest.mark.parametrize("quantos", [0, 1, 7, 60, 250])
def test_o_pareamento_novo_devolve_o_mesmo_que_o_de_antes(
    semente: int, quantos: int
) -> None:
    a, b = _dois_lados(semente, quantos)
    esperado = parear_de_antes(a, b)
    assert parear(a, b) == esperado
    pares = esperado[0]
    assert _um_para_um(pares, b) == um_para_um_de_antes(pares, b)
    # contra si mesmo (todos os itens são iguais ao seu par: empates em toda parte)
    assert parear(a, a) == parear_de_antes(a, a)
    assert parear(list(reversed(a)), a) == parear_de_antes(list(reversed(a)), a)


@pytest.mark.parametrize("tipo", ["aparicao", "plano", "objeto", "pauta"])
def test_um_tipo_so_com_empates_e_pontuais(tipo: Tipo) -> None:
    rng = random.Random(7)
    a = [
        Item(tipo, rng.choice(_NOMES), t, t + d)
        for t in range(0, 6000, 500)
        for d in (0, 1000, 4000)
    ]
    b = a * 2 + [Item(tipo, "ANA", 3000, 3000), Item(tipo, "Ána", 3000, 3000)]
    rng.shuffle(b)
    pares, sem_par = parear(a, b)
    assert (pares, sem_par) == parear_de_antes(a, b)
    assert _um_para_um(pares, b) == um_para_um_de_antes(pares, b)


def test_o_um_para_um_remove_a_primeira_copia_igual() -> None:
    x = Item("plano", "a", 0, 1000)
    y = Item("plano", "b", 0, 1000)
    b = [x, y, x]
    pareados = [
        Pareado(Item("plano", "g", 0, 1000), x),
        Pareado(Item("plano", "h", 0, 1000), y),
    ]
    assert _um_para_um(pareados, b) == um_para_um_de_antes(pareados, b)
    assert _um_para_um(pareados, b)[2] == [x]


def _sintetico(quantos: int) -> tuple[list[Item], list[Item]]:
    """Planos de 2 a 9 s, deslocamento de ±300 ms, 7 identidades (a medição da #639)."""
    rng = random.Random(1)
    a, b = [], []
    for i in range(quantos):
        inicio = i * 2500
        fim = inicio + rng.randrange(2000, 9001)
        nome = _NOMES[i % 7]
        a.append(Item("aparicao", nome, inicio, fim))
        b.append(
            Item(
                "aparicao",
                nome,
                inicio + rng.randrange(-300, 301),
                fim + rng.randrange(-300, 301),
            )
        )
    return a, b


def _tempo(quantos: int) -> float:
    a, b = _sintetico(quantos)
    melhor = float("inf")
    for _ in range(3):
        inicio = time.perf_counter()
        pares, _ = parear(a, b)
        _um_para_um(pares, b)
        melhor = min(melhor, time.perf_counter() - inicio)
    return melhor


def test_tres_mil_itens_em_ate_um_terco_de_segundo_e_seis_mil_em_ate_duas_vezes_e_meia() -> (
    None
):
    # melhor de 3 rodadas, para a carga do CI não pesar; a folga é a da meta aprovada
    t3 = _tempo(3000)
    t6 = _tempo(6000)
    assert t3 <= 0.3, f"3.000 itens levaram {t3:.3f} s"
    assert t6 <= 2.5 * t3, f"6.000 levaram {t6:.3f} s, {t6 / t3:.1f}x o de 3.000"
