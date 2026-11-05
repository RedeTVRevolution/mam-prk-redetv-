"""Programas da emissora (#338): dado vivo no Firestore, editado na administração.

Cada programa tem um id estável (o nome pode mudar), o nome, o perfil em texto e as
pessoas, cada uma com o papel que tem naquele programa. O Job guarda só o nome do
programa; o perfil que o modelo recebe sai do cadastro, nunca de texto livre do envio.
"""

import uuid
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from typing import Annotated, Protocol

from pydantic import BaseModel, StringConstraints

from api.catalogo import Catalogo, visivel

LIMITE_DO_NOME_DO_PROGRAMA = 100
LIMITE_DO_PERFIL = 4000
LIMITE_DO_PAPEL = 100

NomeDoPrograma = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=LIMITE_DO_NOME_DO_PROGRAMA
    ),
]
PerfilEmTexto = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=LIMITE_DO_PERFIL)
]
PapelNoPrograma = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=LIMITE_DO_PAPEL)
]


class VinculoDaPessoa(BaseModel):
    """A pessoa do catálogo no programa e o que ela faz ali."""

    pessoa_id: str
    papel: PapelNoPrograma = ""


class Programa(BaseModel):
    id: str
    nome: NomeDoPrograma
    perfil: PerfilEmTexto = ""
    pessoas: list[VinculoDaPessoa] = []


class ProgramaInexistente(Exception):
    """Nenhum programa tem o id pedido."""


class NomeEmUso(Exception):
    """Já existe outro programa com esse nome."""


def novo_id() -> str:
    return uuid.uuid4().hex


class RepositorioDeProgramas(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def listar(self) -> list[Programa]: ...

    def obter(self, id: str) -> Programa | None: ...

    def salvar(self, programa: Programa) -> None:
        """Grava (cria ou troca) o programa; `NomeEmUso` se outro já tem o nome."""
        ...

    def apagar(self, id: str) -> None:
        """`ProgramaInexistente` se o id não existe."""
        ...


class ProgramasEmMemoria:
    def __init__(self, programas: list[Programa] | None = None) -> None:
        self._programas = {p.id: p for p in programas or []}

    def listar(self) -> list[Programa]:
        return sorted(self._programas.values(), key=lambda p: p.nome.casefold())

    def obter(self, id: str) -> Programa | None:
        return self._programas.get(id)

    def salvar(self, programa: Programa) -> None:
        if any(
            p.id != programa.id and p.nome.casefold() == programa.nome.casefold()
            for p in self._programas.values()
        ):
            raise NomeEmUso(programa.nome)
        self._programas[programa.id] = programa

    def apagar(self, id: str) -> None:
        if self._programas.pop(id, None) is None:
            raise ProgramaInexistente(id)


@dataclass(frozen=True)
class PessoaDoPerfil:
    nome: str
    papel: str
    apelidos: tuple[str, ...] = ()


@dataclass(frozen=True)
class PerfilDoPrograma:
    """O que o modelo lê do programa: o texto do perfil e as pessoas com papel."""

    nome: str
    perfil: str
    pessoas: tuple[PessoaDoPerfil, ...] = ()

    def texto(self) -> str:
        """O perfil, seguido das pessoas frequentes com papel e apelidos."""
        linhas = [self.perfil.strip()]
        if self.pessoas:
            linhas.append("Pessoas frequentes:")
        for p in self.pessoas:
            apelidos = ", ".join(f'"{a}"' for a in p.apelidos)
            linhas.append(
                f"- {p.nome}, {p.papel}"
                + (f"; também chamado de {apelidos}" if apelidos else "")
                + "."
            )
        return "\n".join(linhas)


Perfis = Mapping[str, PerfilDoPrograma]


def perfis_dos_programas(
    repositorio: RepositorioDeProgramas, catalogo: Catalogo
) -> Perfis:
    """Os programas cadastrados agora, pelo nome, com as pessoas lidas do catálogo.
    Quem está na lixeira ou foi fundida em outra não entra."""
    perfis: dict[str, PerfilDoPrograma] = {}
    for programa in repositorio.listar():
        pessoas: list[PessoaDoPerfil] = []
        for vinculo in programa.pessoas:
            pessoa = catalogo.obter(vinculo.pessoa_id)
            if pessoa is not None and visivel(pessoa):
                pessoas.append(
                    PessoaDoPerfil(pessoa.nome, vinculo.papel, tuple(pessoa.apelidos))
                )
        perfis[programa.nome] = PerfilDoPrograma(
            programa.nome, programa.perfil, tuple(pessoas)
        )
    return perfis


class NomesDosProgramas(Collection[str]):
    """Os nomes dos programas cadastrados, lidos do repositório a cada uso: quem guarda
    isto vê o programa novo sem reiniciar."""

    def __init__(self, repositorio: RepositorioDeProgramas) -> None:
        self._repositorio = repositorio

    def _nomes(self) -> list[str]:
        return sorted(p.nome for p in self._repositorio.listar())

    def __iter__(self) -> Iterator[str]:
        return iter(self._nomes())

    def __len__(self) -> int:
        return len(self._nomes())

    def __contains__(self, nome: object) -> bool:
        return nome in self._nomes()
