"""Pareamento de itens da decupagem por tipo, identidade e tempo (#639).

Serve ao comparador do gabarito, ao conjunto de regressão e à comparação de passadas da
tela lado a lado: produção, sem importar ferramenta.
"""

from bisect import bisect_left, bisect_right
from collections import defaultdict
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
    Entre candidatos de mesma sobreposição, vence o de menor desvio de início e de fim
    e, persistindo o empate, o primeiro na ordem do modelo.
    """
    # Grupos por (tipo, identidade normalizada) com os itens do modelo por início, guardando
    # a posição original; só os que começam na janela do item do gabarito são vistos.
    grupos: dict[tuple[str, str], list[tuple[int, int, Item]]] = defaultdict(list)
    for posicao, m in enumerate(modelo):
        grupos[_chave(m)].append((m.inicio_ms, posicao, m))
    inicios: dict[tuple[str, str], list[int]] = {}
    maior_duracao: dict[tuple[str, str], int] = {}
    for chave, itens in grupos.items():
        itens.sort(key=lambda x: (x[0], x[1]))
        inicios[chave] = [x[0] for x in itens]
        maior_duracao[chave] = max(x[2].fim_ms - x[0] for x in itens)
    normalizadas: dict[str, str] = {}
    pareados: list[Pareado] = []
    sem_par: list[Item] = []
    for g in gabarito:
        identidade = ""
        if g.tipo in TIPOS_COM_IDENTIDADE:
            identidade = normalizadas.get(g.identidade) or normalizadas.setdefault(
                g.identidade, normalizar(g.identidade)
            )
        chave = (g.tipo, identidade)
        itens = grupos.get(chave)
        melhor: tuple[int, int, int] | None = None
        escolhido: Item | None = None
        if itens:
            # Um candidato começa em [g.inicio - maior duração, g.fim] (ponytail: uma
            # duração enorme alarga a janela até o grupo todo; árvore de intervalos se for o caso).
            lo = bisect_left(inicios[chave], g.inicio_ms - maior_duracao[chave])
            hi = bisect_right(inicios[chave], g.fim_ms)
            for _, posicao, m in itens[lo:hi]:
                if not se_sobrepoem(g, m):
                    continue
                pontos = (
                    sobreposicao_ms(g, m),
                    -(abs(m.inicio_ms - g.inicio_ms) + abs(m.fim_ms - g.fim_ms)),
                    -posicao,
                )
                if melhor is None or pontos > melhor:
                    melhor, escolhido = pontos, m
        if escolhido is None:
            sem_par.append(g)
        else:
            pareados.append(Pareado(g, escolhido))
    return pareados, sem_par


def _chave(m: Item) -> tuple[str, str]:
    return m.tipo, normalizar(m.identidade) if m.tipo in TIPOS_COM_IDENTIDADE else ""


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
