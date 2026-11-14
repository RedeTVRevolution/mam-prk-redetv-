"""Quem conta (#610): a pergunta única que a leitura faz ao catálogo depois da lixeira, da
purga e da fusão de pessoas.

Um objeto criado a cada operação (uma busca, um relatório, um impacto), dentro dela: lembra o
que já leu, inclusive as ausências e os elos de fusão, então um id é lido uma vez por
operação. Catálogo de pessoas ou de marcas ausente (`None`) quer dizer "sem filtro" para
aquela espécie. Toda leitura do Firestore passa por `lido`: falha vira 503, não 500.

Só a biblioteca padrão, o catálogo e `api.erros`: o módulo de Jobs não entra (sem ciclo).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from api.catalogo import PessoaDoCatalogo
from api.erros import lido
from api.lixeira_na_leitura import (
    PurgaDeMarca,
    PurgasDeMarca,
    conta_depois_do_corte,
)
from api.marcas import CatalogoDeMarcas, MarcaDoCatalogo, nomes_de_busca_da_marca


class PessoasEmLote(Protocol):
    """Do catálogo de pessoas, só o que o Quem conta lê: um lote por vez."""

    def obter_varios(self, ids: Iterable[str]) -> dict[str, PessoaDoCatalogo]: ...


@dataclass(frozen=True)
class Destino:
    """Onde a pessoa pedida acabou: `pessoa` é o registro no fim da cadeia de fusão, ou
    `None` se a pessoa foi purgada, o destino foi purgado ou a cadeia volta sobre si mesma.
    `fundida` diz que a pessoa pedida foi fundida em outra; `origem` é o registro dela.
    `na_lixeira`: algum elo do caminho, o fim incluído, está na lixeira (a pessoa não conta,
    mas a Decupagem corrigida ainda mostra o fim da cadeia).
    """

    pessoa: PessoaDoCatalogo | None
    fundida: bool
    origem: PessoaDoCatalogo | None = None
    na_lixeira: bool = False

    @property
    def conta(self) -> bool:
        return self.pessoa is not None and not self.na_lixeira


@dataclass(frozen=True)
class Cortes:
    """A resposta de `QuemConta.cortes` para os nomes pedidos (normalizados)."""

    fora: frozenset[str]  # nome ou apelido de marca na lixeira: nunca conta
    por_purga: Mapping[str, datetime]  # o corte da purga mais recente do nome

    def tem_corte(self, nome: str) -> bool:
        """O `criado_em` do Job decide: há purga que corta o nome e ele não está na lixeira
        (na lixeira, não conta de qualquer jeito e o Job não precisa ser lido)."""
        return nome in self.por_purga and nome not in self.fora

    def conta(self, nome: str, criado_em: datetime | None) -> bool:
        """O texto da marca conta num Job criado em `criado_em` (Job ausente: `None`, conta
        como anterior à purga)."""
        if nome in self.fora:
            return False
        corte = self.por_purga.get(nome)
        return corte is None or conta_depois_do_corte(criado_em, corte)


class QuemConta:
    def __init__(
        self,
        pessoas: PessoasEmLote | None = None,
        marcas: CatalogoDeMarcas | None = None,
        purgas: PurgasDeMarca | None = None,
    ) -> None:
        self._pessoas = pessoas
        self._marcas = marcas
        self._purgas = purgas
        self._lidas: dict[str, PessoaDoCatalogo | None] = {}
        self._marcas_lidas: dict[str, MarcaDoCatalogo | None] = {}
        self._na_lixeira: frozenset[str] | None = None
        self._todas_as_purgas: list[PurgaDeMarca] | None = None
        self._resolvidos: set[str] = set()
        self._cortes: dict[str, datetime] = {}

    def pessoas(self, ids: Iterable[str]) -> dict[str, Destino]:
        """Para cada id, o destino: segue a cadeia de fusão, lendo em lote um elo de cada vez.
        A cadeia vale de qualquer tamanho; só um id que se repete (ciclo gravado errado) a
        corta, e então a pessoa é tratada como purgada."""
        if self._pessoas is None:
            raise ValueError("sem catálogo de pessoas: use `contam`")
        pedidos = list(dict.fromkeys(ids))
        ponta = {i: i for i in pedidos}  # o id pedido -> onde a cadeia está agora
        vistos = {i: {i} for i in pedidos}
        destinos: dict[str, Destino] = {}
        while ponta:
            self._ler_pessoas(ponta.values())
            for pedido, onde in list(ponta.items()):
                origem, pessoa = self._lidas[pedido], self._lidas[onde]
                fundida = origem is not None and origem.fundida is not None
                lixeira = any(
                    (elo := self._lidas.get(v)) is not None and elo.lixeira is not None
                    for v in vistos[pedido]
                )
                if pessoa is None or pessoa.fundida is None:
                    destinos[pedido] = Destino(pessoa, fundida, origem, lixeira)
                elif pessoa.fundida.destino_id in vistos[pedido]:
                    destinos[pedido] = Destino(None, True, origem, lixeira)
                else:
                    vistos[pedido].add(pessoa.fundida.destino_id)
                    ponta[pedido] = pessoa.fundida.destino_id
                    continue
                del ponta[pedido]
        return {i: destinos[i] for i in pedidos}

    def contam(self, ids: Iterable[str]) -> set[str]:
        """Os `ids` de pessoa que contam; sem catálogo, todos."""
        if self._pessoas is None:
            return set(ids)
        return {i for i, d in self.pessoas(ids).items() if d.conta}

    def marcas_vivas(self, ids: Iterable[str]) -> set[str]:
        """Os ids de marca que existem fora da lixeira; sem catálogo, todos."""
        pedidos = list(dict.fromkeys(ids))
        if self._marcas is None:
            return set(pedidos)
        self._ler_marcas(pedidos)
        return {
            i for i in pedidos if (m := self._marcas_lidas[i]) and m.lixeira is None
        }

    def cortes(self, nomes: Iterable[str], *, so_a_purga: bool = False) -> Cortes:
        """O que conta, para os `nomes` normalizados de marca. O corte de um nome é o da
        purga mais recente que o contém, em qualquer número de consultas. Com `so_a_purga`
        a lixeira não entra (o impacto mostrado antes de enviar, restaurar ou purgar)."""
        if self._marcas is None:
            return Cortes(frozenset(), {})
        nomes = set(nomes)
        self._resolver_cortes(nomes)
        return Cortes(
            frozenset() if so_a_purga else self._nomes_na_lixeira(self._marcas),
            {n: self._cortes[n] for n in nomes if n in self._cortes},
        )

    def _ler_pessoas(self, ids: Iterable[str]) -> None:
        assert self._pessoas is not None
        pessoas = self._pessoas
        faltam = [i for i in dict.fromkeys(ids) if i not in self._lidas]
        if faltam:
            achadas = lido(lambda: pessoas.obter_varios(faltam))
            self._lidas.update({i: achadas.get(i) for i in faltam})

    def _ler_marcas(self, ids: Iterable[str]) -> None:
        assert self._marcas is not None
        marcas = self._marcas
        faltam = [i for i in dict.fromkeys(ids) if i not in self._marcas_lidas]
        if faltam:
            achadas = lido(lambda: marcas.obter_varios(faltam))
            self._marcas_lidas.update({i: achadas.get(i) for i in faltam})

    def _nomes_na_lixeira(self, marcas: CatalogoDeMarcas) -> frozenset[str]:
        if self._na_lixeira is None:
            self._na_lixeira = frozenset(
                n for m in lido(marcas.na_lixeira) for n in nomes_de_busca_da_marca(m)
            )
        return self._na_lixeira

    def _resolver_cortes(self, nomes: set[str]) -> None:
        """Resolve os nomes ainda não vistos, um a um: só a purga que vale conta (a de uma
        marca que ainda existe não terminou; a da homônima recriada vale, o id é outro)."""
        novos = nomes - self._resolvidos
        if not novos:
            return
        if self._todas_as_purgas is None:
            self._todas_as_purgas = lido(self._purgas.todas) if self._purgas else []
        achadas = [p for p in self._todas_as_purgas if novos & set(p.nomes)]
        self._ler_marcas(p.marca_id for p in achadas if p.marca_id)
        for p in achadas:
            if p.marca_id is None or self._marcas_lidas[p.marca_id] is None:
                for n in novos & set(p.nomes):
                    self._cortes[n] = max(p.em, self._cortes.get(n, p.em))
        self._resolvidos |= novos
