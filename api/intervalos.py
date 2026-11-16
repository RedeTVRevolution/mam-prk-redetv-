"""A conta de sobreposição de intervalos, com uma função por regra de borda.

Cada intervalo é `[inicio, fim]` em ms (ou em segundos, onde o chamador já os usa).
As regras diferem só na borda: escolha pelo nome, não escreva a conta à mão.
"""


def sobrepoe_estrito(a_ini: float, a_fim: float, b_ini: float, b_fim: float) -> bool:
    """Trecho em comum maior que zero: intervalos que só se encostam não se sobrepõem."""
    return a_ini < b_fim and b_ini < a_fim


def sobrepoe_inclusivo(a_ini: float, a_fim: float, b_ini: float, b_fim: float) -> bool:
    """Encostar conta: o fim de um igual ao início do outro já é sobreposição."""
    return a_ini <= b_fim and b_ini <= a_fim


def sobrepoe_com_folga(
    a_ini: float, a_fim: float, b_ini: float, b_fim: float, folga: float
) -> bool:
    """Como a estrita, mas `a` vale `folga` a mais de cada lado (borda estrita)."""
    return a_ini - folga < b_fim and b_ini < a_fim + folga


def comprimento_da_sobreposicao[T: (int, float)](
    a_ini: T, a_fim: T, b_ini: T, b_fim: T
) -> T:
    """Tamanho do trecho em comum; negativo (a distância) quando não há trecho."""
    return min(a_fim, b_fim) - max(a_ini, b_ini)


def sobrepoe_de_verdade(a_ini: int, a_fim: int, b_ini: int, b_fim: int) -> bool:
    """Sobreposição positiva, ou instante (duração zero) que cai dentro do outro."""
    c = comprimento_da_sobreposicao(a_ini, a_fim, b_ini, b_fim)
    return c > 0 or (c == 0 and (a_ini == a_fim or b_ini == b_fim))


def sobrepoe_metade(a_ini: int, a_fim: int, b_ini: int, b_fim: int) -> bool:
    """A sobreposição cobre pelo menos metade do menor dos dois intervalos.

    Um intervalo de duração zero (um instante) conta se cai dentro do outro.
    """
    c = comprimento_da_sobreposicao(a_ini, a_fim, b_ini, b_fim)
    return c >= 0 and c * 2 >= min(a_fim - a_ini, b_fim - b_ini)
