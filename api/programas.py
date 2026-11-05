"""Programas da emissora (#338): dado vivo no Firestore, editado na administração.

Cada programa tem um id estável (o nome pode mudar), o nome, o perfil em texto e as
pessoas, cada uma com o papel que tem naquele programa. O Job guarda só o nome do
programa; o perfil que o modelo recebe sai do cadastro, nunca de texto livre do envio.
"""

import uuid
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol

from pydantic import BaseModel, StringConstraints

from api.catalogo import Catalogo, visivel

if TYPE_CHECKING:  # `api.jobs` importa este módulo
    from api.jobs import Job, RepositorioDeJobs

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


class RenomeacaoDoPrograma(BaseModel):
    """A troca do nome nos vídeos (o Job guarda o nome), com os que ainda faltam.

    `confirmando`: o nome novo já está gravado, mas a auditoria ainda não; nada mexe nos
    vídeos até a troca passar a `em_andamento`. `id` separa uma troca da que a substitui.
    """

    id: str = ""  # sem fábrica: o andamento gravado sem id é lido sempre igual
    nome_antigo: str
    nome_novo: str
    total: int
    pendentes: list[str]  # ids dos Jobs ainda por trocar e reindexar
    estado: Literal["confirmando", "em_andamento", "concluida", "falhou"]
    desde: datetime | None = None  # quando a troca foi pedida


class Programa(BaseModel):
    id: str
    nome: NomeDoPrograma
    perfil: PerfilEmTexto = ""
    pessoas: list[VinculoDaPessoa] = []
    renomeacao: RenomeacaoDoPrograma | None = None


class ProgramaInexistente(Exception):
    """Nenhum programa tem o id pedido."""


class NomeEmUso(Exception):
    """Já existe outro programa com esse nome."""


class TrocaSubstituida(Exception):
    """A troca de nome não está mais em andamento no programa (outra tomou o lugar, ela
    terminou ou o programa sumiu): a tarefa dela não escreve mais nada."""


def troca_vale(programa: "Programa | None", troca_id: str) -> bool:
    """O programa existe e a troca `troca_id` é a dele, em andamento."""
    r = programa.renomeacao if programa else None
    return r is not None and r.id == troca_id and r.estado == "em_andamento"


def novo_id() -> str:
    return uuid.uuid4().hex


class RepositorioDeProgramas(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def listar(self) -> list[Programa]: ...

    def obter(self, id: str) -> Programa | None: ...

    def salvar(self, programa: Programa, *, com_renomeacao: bool = False) -> None:
        """Grava (cria ou troca) o programa; `NomeEmUso` se outro já tem o nome. Sem
        `com_renomeacao`, o andamento gravado fica como está (a tarefa o muda sozinha)."""
        ...

    def trocar(
        self, id: str, mudar: Callable[[Programa], Programa | None]
    ) -> Programa | None:
        """Lê e grava de uma vez (transação): `mudar` recebe o gravado e devolve o novo,
        ou `None` para não gravar. Devolve o gravado, ou `None` se nada foi gravado ou o
        programa não existe; `NomeEmUso` se o nome novo é de outro."""
        ...

    def levar_o_nome_ao_job(
        self, programa_id: str, troca_id: str, job_id: str, jobs: "RepositorioDeJobs"
    ) -> "Job | None":
        """Grava no Job o nome do programa, lido junto com o Job (na mesma transação),
        se a troca `troca_id` ainda está em andamento nele, e devolve o Job; `None` se o
        Job não existe. `TrocaSubstituida` (sem gravar nada) se a troca não vale mais:
        uma tarefa atrasada nunca escreve no Job."""
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

    def _conferir_nome(self, programa: Programa) -> None:
        if any(
            p.id != programa.id and p.nome.casefold() == programa.nome.casefold()
            for p in self._programas.values()
        ):
            raise NomeEmUso(programa.nome)

    def salvar(self, programa: Programa, *, com_renomeacao: bool = False) -> None:
        self._conferir_nome(programa)
        if not com_renomeacao:
            atual = self._programas.get(programa.id)
            programa = programa.model_copy(
                update={"renomeacao": atual.renomeacao if atual else None}
            )
        self._programas[programa.id] = programa

    def trocar(
        self, id: str, mudar: Callable[[Programa], Programa | None]
    ) -> Programa | None:
        atual = self._programas.get(id)
        novo = mudar(atual) if atual is not None else None
        if novo is None:
            return None
        self._conferir_nome(novo)
        self._programas[id] = novo
        return novo

    def levar_o_nome_ao_job(
        self, programa_id: str, troca_id: str, job_id: str, jobs: "RepositorioDeJobs"
    ) -> "Job | None":
        def mudar(job: "Job") -> dict[str, Any] | None:
            # Lido na hora de gravar o Job, como na transação do Firestore.
            programa = self._programas.get(programa_id)
            if programa is None or not troca_vale(programa, troca_id):
                raise TrocaSubstituida(troca_id)
            return (
                None if job.programa == programa.nome else {"programa": programa.nome}
            )

        trocado = jobs.trocar(job_id, mudar)
        if trocado is not None:
            return trocado
        if not troca_vale(self._programas.get(programa_id), troca_id):
            raise TrocaSubstituida(troca_id)
        return jobs.obter(job_id)

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
