"""Rotas do autocompletar de pessoas e marcas (#150).

`GET` com `decupagem.ver` busca por prefixo (veja `achar_nomes`); `POST` com
`decupagem.editar` acrescenta o nome digitado como "a revisar", para o Curador
conferir, ou devolve o que já existe com esse nome. O catálogo é pequeno: a busca
corre em memória, sobre uma cópia que vale poucos segundos. O cadastro de marcas do
Curador (apelidos e juntar) fica em `api.cadastro_de_marcas`.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, field_validator

from api.achar_nomes import IndiceDeNomes, achar_por_prefixo
from api.auditoria import RepositorioDeAuditoria
from api.auth import Usuario
from api.cadastro_de_marcas import criar_rotas_do_cadastro_de_marcas
from api.catalogo import (
    Catalogo,
    CopiaCurta,
    PessoaDoCatalogo,
    existente_para_acrescentar,
)
from api.correcoes import LIMITE_DO_NOME, sem_controle
from api.marcas import CatalogoDeMarcas, MarcaDoCatalogo
from api.permissoes import exige, exige_escopo
from api.texto_como_dado import Linha, LinhaDaConsulta

Nome = Annotated[
    str,
    Linha(LIMITE_DO_NOME, min_length=1, strip=True),
]


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
    papel: Annotated[str, Linha(LIMITE_DO_NOME, strip=True)] = ""

    _sem_controle_no_nome = field_validator("nome", "papel")(sem_controle)


class NovaMarca(BaseModel):
    nome: Nome

    _sem_controle_no_nome = field_validator("nome")(sem_controle)


def _rotulo(nome: str, papel: str) -> str:
    return f"{nome} ({papel})" if papel else nome


def criar_rotas_do_catalogo(
    pessoas: Catalogo,
    marcas: CatalogoDeMarcas,
    relogio: Callable[[], datetime],
    fusao: Callable[[Callable[[], None]], APIRouter],
    auditoria: RepositorioDeAuditoria,
    copia_das_pessoas: CopiaCurta[PessoaDoCatalogo] | None = None,
    avancar_a_versao: Callable[[], None] = lambda: None,
) -> APIRouter:
    """`fusao` monta as rotas de fundir pessoas (#209); recebe como descartar a cópia
    da lista de pessoas, para a fundida sair do autocompletar na hora. `copia_das_pessoas`
    é a cópia que a busca também usa para resolver nomes. `avancar_a_versao` invalida os
    cursores da busca quando o cadastro de marcas muda quem é cada marca."""
    rotas = APIRouter(prefix="/catalogo")
    copia_das_pessoas = copia_das_pessoas or CopiaCurta(pessoas.todas, relogio)
    copia_das_marcas = CopiaCurta(marcas.todas, relogio)
    # Os nomes normalizados valem por cópia: uma cópia nova refaz o índice (#484).
    indice_das_pessoas = IndiceDeNomes[PessoaDoCatalogo]()
    indice_das_marcas = IndiceDeNomes[MarcaDoCatalogo]()

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

    @rotas.get("/pessoas", dependencies=[Depends(exige_escopo("ler"))])
    def achar_pessoas(
        q: Annotated[str, LinhaDaConsulta(LIMITE_DO_NOME)],
    ) -> list[PessoaAchada]:
        achadas = achar_por_prefixo(indice_das_pessoas.de(copia_das_pessoas.itens()), q)
        return [pessoa_achada(p) for p in achadas]

    @rotas.post("/pessoas")
    def acrescentar_pessoa(
        nova: NovaPessoa,
        resposta: Response,
        autor: Annotated[
            Usuario,
            Depends(
                exige("decupagem.editar", "Chave de sistema não corrige a decupagem")
            ),
        ],
    ) -> PessoaAchada:
        existente = existente_para_acrescentar(
            pessoas.achar(nova.nome, com_lixeira=True)
        )
        if existente:
            return pessoa_achada(existente)
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

    @rotas.get("/marcas", dependencies=[Depends(exige_escopo("ler"))])
    def achar_marcas(
        q: Annotated[str, LinhaDaConsulta(LIMITE_DO_NOME)],
    ) -> list[MarcaAchada]:
        achadas = achar_por_prefixo(indice_das_marcas.de(copia_das_marcas.itens()), q)
        return [marca_achada(m) for m in achadas]

    @rotas.post("/marcas")
    def acrescentar_marca(
        nova: NovaMarca,
        resposta: Response,
        autor: Annotated[
            Usuario,
            Depends(
                exige("decupagem.editar", "Chave de sistema não corrige a decupagem")
            ),
        ],
    ) -> MarcaAchada:
        existente = existente_para_acrescentar(
            marcas.achar(nova.nome, com_lixeira=True)
        )
        if existente:
            return marca_achada(existente)
        resposta.status_code = 201
        criada = marcas.acrescentar(
            nova.nome, [], a_revisar=True, autor=autor.email or autor.uid
        )
        copia_das_marcas.descartar()
        return marca_achada(criada)

    rotas.include_router(fusao(copia_das_pessoas.descartar))

    def _descartar_marcas() -> None:
        copia_das_marcas.descartar()
        avancar_a_versao()

    rotas.include_router(
        criar_rotas_do_cadastro_de_marcas(marcas, auditoria, relogio, _descartar_marcas)
    )
    return rotas
