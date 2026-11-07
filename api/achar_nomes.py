"""Autocompletar de nomes (#150): a busca do catálogo de pessoas e do de marcas.

Corre em memória sobre o catálogo, que é pequeno. Sem diferença de acento
nem de maiúscula; cada termo digitado tem de começar uma palavra do nome (ou de um
apelido); termos de 5 letras ou mais aceitam um erro de digitação (uma letra a
mais, a menos, trocada, ou duas vizinhas trocadas).

Os casamentos exatos vêm de um índice por palavra (#485): lista ordenada de (palavra,
posição do item, variante), consultada com `bisect` pelo prefixo de cada termo, sem
varrer o catálogo. Só quando os exatos não enchem o limite e algum termo aceita erro de
digitação o resto do catálogo é percorrido, para completar com os aproximados.
"""

from bisect import bisect_left
from collections.abc import Iterable
from typing import Protocol

from api.comparador import normalizar

LIMITE_DO_AUTOCOMPLETAR = 10
TAMANHO_PARA_ACEITAR_ERRO = 5


class ComNome(Protocol):
    @property
    def nome(self) -> str: ...

    @property
    def apelidos(self) -> list[str]: ...


def _distancia(a: str, b: str) -> int:
    """Distância de edição com troca de duas letras vizinhas contando como uma."""
    linhas = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        linhas[i][0] = i
    for j in range(len(b) + 1):
        linhas[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            custo = 0 if a[i - 1] == b[j - 1] else 1
            linhas[i][j] = min(
                linhas[i - 1][j] + 1, linhas[i][j - 1] + 1, linhas[i - 1][j - 1] + custo
            )
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                linhas[i][j] = min(linhas[i][j], linhas[i - 2][j - 2] + 1)
    return linhas[len(a)][len(b)]


def _custo_do_termo(termo: str, palavra: str) -> int | None:
    """0 se `termo` começa `palavra`; 1 se casa com um erro de digitação; senão `None`."""
    if palavra.startswith(termo):
        return 0
    if len(termo) < TAMANHO_PARA_ACEITAR_ERRO:
        return None
    for tamanho in (len(termo) - 1, len(termo), len(termo) + 1):
        if _distancia(termo, palavra[:tamanho]) <= 1:
            return 1
    return None


def _custo_no_nome(termos: list[str], nome: str) -> int | None:
    palavras = nome.split()
    total = 0
    for termo in termos:
        custos = [c for p in palavras if (c := _custo_do_termo(termo, p)) is not None]
        if not custos:
            return None
        total += min(custos)
    return total


class Indexado[T: ComNome]:
    """Um item com o nome e os apelidos já normalizados (#484)."""

    __slots__ = ("item", "nome", "nomes")

    def __init__(self, item: T) -> None:
        self.item = item
        self.nome = normalizar(item.nome)
        self.nomes = [self.nome, *(normalizar(a) for a in item.apelidos)]


def _custo_minimo[T: ComNome](termos: list[str], indexado: Indexado[T]) -> int | None:
    """O menor custo dos termos entre o nome e os apelidos; `None` se nenhum casa."""
    custos = [
        c for nome in indexado.nomes if (c := _custo_no_nome(termos, nome)) is not None
    ]
    return min(custos) if custos else None


class ListaIndexada[T: ComNome](list[Indexado[T]]):
    """Os itens indexados de uma cópia, mais o índice por palavra (#485): entradas
    `(palavra, posição do item, variante)` em ordem; a variante 0 é o nome, as outras os apelidos."""

    def __init__(self, itens: Iterable[T]) -> None:
        super().__init__(Indexado(i) for i in itens)
        self.palavras = sorted(
            (palavra, posicao, variante)
            for posicao, indexado in enumerate(self)
            for variante, nome in enumerate(indexado.nomes)
            for palavra in set(nome.split())
        )

    def posicoes_exatas(self, termos: list[str]) -> set[int]:
        """Posições dos itens com uma variante em que todos os termos começam uma palavra."""
        comuns: set[tuple[int, int]] | None = None
        for termo in termos:
            casam: set[tuple[int, int]] = set()
            for i in range(bisect_left(self.palavras, (termo,)), len(self.palavras)):
                palavra, posicao, variante = self.palavras[i]
                if not palavra.startswith(termo):
                    break
                casam.add((posicao, variante))
            comuns = casam if comuns is None else comuns & casam
            if not comuns:
                return set()
        return {p for p, _ in comuns or ()}


class IndiceDeNomes[T: ComNome]:
    """Os nomes normalizados e o índice por palavra de uma cópia do catálogo, calculados
    uma vez por cópia. `de` recebe a lista que a `CopiaCurta` devolve: enquanto for a
    mesma lista, reaproveita; uma cópia nova (outra lista) refaz o índice."""

    def __init__(self) -> None:
        self._atual: tuple[list[T], ListaIndexada[T]] | None = None

    def de(self, itens: list[T]) -> ListaIndexada[T]:
        atual = self._atual
        if atual is not None and atual[0] is itens:
            return atual[1]
        indexados = ListaIndexada(itens)
        self._atual = (itens, indexados)
        return indexados


def achar_por_prefixo[T: ComNome](
    itens: Iterable[T] | Iterable[Indexado[T]],
    consulta: str,
    limite: int = LIMITE_DO_AUTOCOMPLETAR,
) -> list[T]:
    """Até `limite` itens que a consulta casa no nome ou nos apelidos: primeiro os sem
    erro de digitação, depois os com; dentro de cada grupo, por nome. Com `IndiceDeNomes`
    os nomes não são normalizados de novo a cada pedido, e os exatos vêm do índice por
    palavra; sem ele (itens crus) tudo é percorrido."""
    termos = normalizar(consulta).split()
    if not termos:
        return []
    if isinstance(itens, ListaIndexada):
        exatos = sorted(itens.posicoes_exatas(termos), key=lambda p: (itens[p].nome, p))
        aceita_erro = any(len(t) >= TAMANHO_PARA_ACEITAR_ERRO for t in termos)
        if 0 <= limite <= len(exatos) or not aceita_erro:
            return [itens[p].item for p in exatos[:limite]]
        ja_achados = set(exatos)
        aproximados = [
            (custo, indexado.nome, indexado.item)
            for posicao, indexado in enumerate(itens)
            if posicao not in ja_achados
            and (custo := _custo_minimo(termos, indexado)) is not None
        ]
        aproximados.sort(key=lambda a: (a[0], a[1]))
        juntos = [itens[p].item for p in exatos] + [item for _, _, item in aproximados]
        return juntos[:limite]
    achados: list[tuple[int, str, T]] = []
    for entrada in itens:
        indexado = entrada if isinstance(entrada, Indexado) else Indexado(entrada)
        custo = _custo_minimo(termos, indexado)
        if custo is not None:
            achados.append((custo, indexado.nome, indexado.item))
    achados.sort(key=lambda a: (a[0], a[1]))
    return [item for _, _, item in achados[:limite]]
