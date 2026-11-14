"""Pareamento de itens da decupagem por tipo, identidade e tempo (#639).

Serve ao comparador do gabarito, ao conjunto de regressão e à comparação de passadas da
tela lado a lado: produção, sem importar ferramenta.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, get_args

from api.decupagem import Decupagem
from api.texto import normalizar

Tipo = Literal[
    "aparicao",
    "mencao",
    "pauta",
    "comercial",
    "plano",
    "fala",
    "texto_na_tela",
    "objeto",
    "bloco",
]
TIPOS: tuple[Tipo, ...] = get_args(Tipo)
TIPOS_COM_IDENTIDADE: frozenset[Tipo] = frozenset(
    {"aparicao", "mencao", "comercial", "texto_na_tela", "objeto"}
)  # pauta, plano, fala e bloco: só tempo
TOLERANCIA_MS = 2000


@dataclass(frozen=True)
class Item:
    tipo: Tipo
    identidade: str
    inicio_ms: int
    fim_ms: int


@dataclass(frozen=True)
class Pareado:
    gabarito: Item
    modelo: Item

    @property
    def erro_inicio_ms(self) -> int:
        return abs(self.modelo.inicio_ms - self.gabarito.inicio_ms)

    @property
    def erro_fim_ms(self) -> int:
        return abs(self.modelo.fim_ms - self.gabarito.fim_ms)

    @property
    def erro_ms(self) -> int:
        return max(self.erro_inicio_ms, self.erro_fim_ms)

    @property
    def dentro(self) -> bool:
        return self.erro_ms <= TOLERANCIA_MS


def sobreposicao_ms(a: Item, b: Item) -> int:
    return min(a.fim_ms, b.fim_ms) - max(a.inicio_ms, b.inicio_ms)


def se_sobrepoem(a: Item, b: Item) -> bool:
    """Têm trecho em comum; um item pontual (início = fim) vale se cair no outro."""
    s = sobreposicao_ms(a, b)
    return s > 0 or (s == 0 and (a.inicio_ms == a.fim_ms or b.inicio_ms == b.fim_ms))


def parear(
    gabarito: Iterable[Item], modelo: list[Item]
) -> tuple[list[Pareado], list[Item]]:
    """Pareia cada item do gabarito com o do modelo de maior sobreposição.

    Mesmo tipo; aparição, menção e comercial exigem também a mesma identidade.
    Sem trecho em comum, não há par; item pontual pareia com o que o contém.
    """
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


def itens_do_modelo(d: Decupagem) -> list[Item]:
    itens = [Item("pauta", p.titulo, p.inicio_ms, p.fim_ms) for p in d.pautas]
    itens += [Item("comercial", c.marca, c.inicio_ms, c.fim_ms) for c in d.comerciais]
    for p in d.pessoas:
        itens += [Item("aparicao", p.nome, a.inicio_ms, a.fim_ms) for a in p.na_imagem]
        for m in [*p.citada_na_fala, *p.citada_no_texto]:
            itens.append(Item("mencao", p.nome, m.inicio_ms, m.fim_ms))
    itens += [Item("plano", p.ambiente, p.inicio_ms, p.fim_ms) for p in d.planos]
    itens += [Item("fala", f.locutor, f.inicio_ms, f.fim_ms) for f in d.transcricao]
    itens += [
        Item("texto_na_tela", t.texto, t.inicio_ms, t.fim_ms) for t in d.textos_na_tela
    ]
    for o in d.objetos:
        itens += [Item("objeto", o.tipo, i.inicio_ms, i.fim_ms) for i in o.ocorrencias]
    itens += [Item("bloco", b.titulo, b.inicio_ms, b.fim_ms) for b in d.programa.blocos]
    return itens
