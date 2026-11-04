"""Rotas do autocompletar de pessoas e marcas (#150).

`GET` com `decupagem.ver` busca por prefixo (veja `achar_nomes`); `POST` com
`decupagem.editar` acrescenta o nome digitado como "a revisar", para o Curador
conferir, ou devolve o que já existe com esse nome. O catálogo é pequeno: a busca
corre em memória, sobre uma cópia que vale poucos segundos.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, StringConstraints, field_validator

from api.achar_nomes import ComNome, achar_por_prefixo
from api.auth import Usuario
from api.catalogo import Catalogo, PessoaDoCatalogo
from api.correcoes import LIMITE_DO_NOME, _sem_controle
from api.jobs import _exige, _exige_editar
from api.marcas import CatalogoDeMarcas, MarcaDoCatalogo

VALIDADE_DA_COPIA = timedelta(seconds=30)

Nome = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME),
]


class _Catalogavel(ComNome, Protocol):
    @property
    def id(self) -> str: ...


class _CopiaCurta[T: _Catalogavel]:
    """A lista do catálogo lida há pouco; um nome acrescentado aqui a descarta."""

    def __init__(self, ler: Callable[[], list[T]], relogio: Callable[[], datetime]):
        self._ler, self._relogio = ler, relogio
        self._lida_em: datetime | None = None
        self._itens: list[T] = []

    def itens(self) -> list[T]:
        agora = self._relogio()
        if self._lida_em is None or agora - self._lida_em >= VALIDADE_DA_COPIA:
            self._itens, self._lida_em = self._ler(), agora
        return self._itens

    def descartar(self) -> None:
        self._lida_em = None


class PessoaAchada(BaseModel):
    id: str
    nome: str
    papel: str
    # "Sabrina Sato (apresentadora)": o que o autocompletar mostra.
    rotulo: str
    a_revisar: bool


class MarcaAchada(BaseModel):
    id: str
    nome: str
    a_revisar: bool


class NovaPessoa(BaseModel):
    nome: Nome
    papel: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=LIMITE_DO_NOME)
    ] = ""

    _sem_controle_no_nome = field_validator("nome", "papel")(_sem_controle)


class NovaMarca(BaseModel):
    nome: Nome

    _sem_controle_no_nome = field_validator("nome")(_sem_controle)


def _rotulo(nome: str, papel: str) -> str:
    return f"{nome} ({papel})" if papel else nome


def criar_rotas_do_catalogo(
    pessoas: Catalogo,
    marcas: CatalogoDeMarcas,
    relogio: Callable[[], datetime],
    fusao: Callable[[Callable[[], None]], APIRouter],
) -> APIRouter:
    """`fusao` monta as rotas de fundir pessoas (#209); recebe como descartar a cópia
    da lista de pessoas, para a fundida sair do autocompletar na hora."""
    rotas = APIRouter(prefix="/catalogo")
    copia_das_pessoas = _CopiaCurta(pessoas.todas, relogio)
    copia_das_marcas = _CopiaCurta(marcas.todas, relogio)

    def pessoa_achada(p: PessoaDoCatalogo) -> PessoaAchada:
        return PessoaAchada(
            id=p.id,
            nome=p.nome,
            papel=p.papel,
            rotulo=_rotulo(p.nome, p.papel),
            a_revisar=p.a_revisar,
        )

    def marca_achada(m: MarcaDoCatalogo) -> MarcaAchada:
        return MarcaAchada(id=m.id, nome=m.nome, a_revisar=m.a_revisar)

    @rotas.get("/pessoas", dependencies=[Depends(_exige("ler"))])
    def achar_pessoas(
        q: Annotated[str, Query(max_length=LIMITE_DO_NOME)],
    ) -> list[PessoaAchada]:
        achadas = achar_por_prefixo(copia_das_pessoas.itens(), q)
        return [pessoa_achada(p) for p in achadas]

    @rotas.post("/pessoas")
    def acrescentar_pessoa(
        nova: NovaPessoa,
        resposta: Response,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> PessoaAchada:
        existentes = pessoas.achar(nova.nome)
        if existentes:
            return pessoa_achada(existentes[0])
        resposta.status_code = 201
        criada = pessoas.acrescentar(
            nova.nome,
            nova.papel,
            [],
            a_revisar=True,
            autor=autor.email or autor.uid,
        )
        copia_das_pessoas.descartar()
        return pessoa_achada(criada)

    @rotas.get("/marcas", dependencies=[Depends(_exige("ler"))])
    def achar_marcas(
        q: Annotated[str, Query(max_length=LIMITE_DO_NOME)],
    ) -> list[MarcaAchada]:
        achadas = achar_por_prefixo(copia_das_marcas.itens(), q)
        return [marca_achada(m) for m in achadas]

    @rotas.post("/marcas")
    def acrescentar_marca(
        nova: NovaMarca,
        resposta: Response,
        autor: Annotated[Usuario, Depends(_exige_editar)],
    ) -> MarcaAchada:
        existentes = marcas.achar(nova.nome)
        if existentes:
            return marca_achada(existentes[0])
        resposta.status_code = 201
        criada = marcas.acrescentar(
            nova.nome, [], a_revisar=True, autor=autor.email or autor.uid
        )
        copia_das_marcas.descartar()
        return marca_achada(criada)

    rotas.include_router(fusao(copia_das_pessoas.descartar))
    return rotas
