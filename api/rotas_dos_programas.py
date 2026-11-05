"""Rotas da aba Programas da administração (#338).

Quem tem `programas.editar` (Editor, Curador e Administrador) cria, edita e apaga
programas, inclui pessoas do catálogo com o papel que têm no programa e cria a
pessoa que ainda não existe. Toda mudança vai para a auditoria; se o registro não
for gravado, a mudança é desfeita.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, StringConstraints, field_validator

from api.auditoria import Acao, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.catalogo import Catalogo, visivel
from api.correcoes import _sem_controle
from api.jobs import FiltroDeJobs, RepositorioDeJobs, _confere_permissao
from api.programas import (
    NomeDoPrograma,
    NomeEmUso,
    PerfilEmTexto,
    Programa,
    ProgramaInexistente,
    RepositorioDeProgramas,
    VinculoDaPessoa,
    novo_id,
)

LIMITE_DE_APELIDOS = 20
LIMITE_DO_APELIDO = 100
LIMITE_DE_PESSOAS_NO_PROGRAMA = 200

Apelido = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=LIMITE_DO_APELIDO
    ),
]


class PessoaNoProgramaPublica(BaseModel):
    pessoa_id: str
    nome: str
    apelidos: list[str]
    papel: str


class ProgramaPublico(BaseModel):
    id: str
    nome: str
    perfil: str
    pessoas: list[PessoaNoProgramaPublica]


class DadosDoPrograma(BaseModel):
    nome: NomeDoPrograma
    perfil: PerfilEmTexto = ""
    pessoas: list[VinculoDaPessoa] = []

    _sem_controle_no_nome = field_validator("nome")(_sem_controle)

    @field_validator("perfil")
    @classmethod
    def _perfil_sem_controle(cls, perfil: str) -> str:
        # Várias linhas, como o texto que o modelo lê.
        return _sem_controle(perfil.replace("\r\n", "\n"), permitidos="\n")

    @field_validator("pessoas")
    @classmethod
    def _pessoas_validas(cls, pessoas: list[VinculoDaPessoa]) -> list[VinculoDaPessoa]:
        if len(pessoas) > LIMITE_DE_PESSOAS_NO_PROGRAMA:
            raise ValueError("pessoas demais no programa")
        ids = [p.pessoa_id for p in pessoas]
        if len(set(ids)) != len(ids):
            raise ValueError("a mesma pessoa duas vezes no programa")
        for p in pessoas:
            _sem_controle(p.papel)
        return pessoas


class NovaPessoaDoPrograma(BaseModel):
    nome: NomeDoPrograma
    apelidos: list[Apelido] = []

    _sem_controle_no_nome = field_validator("nome")(_sem_controle)

    @field_validator("apelidos")
    @classmethod
    def _apelidos_validos(cls, apelidos: list[str]) -> list[str]:
        if len(apelidos) > LIMITE_DE_APELIDOS:
            raise ValueError("apelidos demais")
        return [_sem_controle(a) for a in apelidos]


class ImpactoDoPrograma(BaseModel):
    videos: int


def _exige_editar_programas(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `programas.editar`; chave de sistema não edita."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não edita programas")
    _confere_permissao(request, chamador, "programas.editar")
    return chamador


def criar_rotas_dos_programas(
    programas: RepositorioDeProgramas,
    catalogo: Catalogo,
    jobs: RepositorioDeJobs,
    auditoria: RepositorioDeAuditoria,
    relogio: Callable[[], datetime],
) -> APIRouter:
    rotas = APIRouter(prefix="/admin/programas")

    def publico(programa: Programa) -> ProgramaPublico:
        pessoas: list[PessoaNoProgramaPublica] = []
        for v in programa.pessoas:
            pessoa = catalogo.obter(v.pessoa_id)
            if pessoa is not None and visivel(pessoa):
                pessoas.append(
                    PessoaNoProgramaPublica(
                        pessoa_id=pessoa.id,
                        nome=pessoa.nome,
                        apelidos=pessoa.apelidos,
                        papel=v.papel,
                    )
                )
        return ProgramaPublico(
            id=programa.id, nome=programa.nome, perfil=programa.perfil, pessoas=pessoas
        )

    def conferir_pessoas(dados: DadosDoPrograma) -> None:
        for v in dados.pessoas:
            pessoa = catalogo.obter(v.pessoa_id)
            if pessoa is None or not visivel(pessoa):
                raise HTTPException(422, f"Pessoa fora do catálogo: {v.pessoa_id}")

    def gravar(programa: Programa) -> None:
        try:
            programas.salvar(programa)
        except NomeEmUso:
            raise HTTPException(409, "Já existe um programa com esse nome") from None

    def registrar(
        acao: Acao,
        autor: Usuario,
        programa: Programa,
        antes: Programa | None,
        depois: Programa | None,
        desfazer: Callable[[], None],
    ) -> None:
        try:
            auditoria.acrescentar(
                RegistroDeAuditoria(
                    id=uuid.uuid4().hex,
                    quando=relogio(),
                    uid=autor.uid,
                    email=autor.email,
                    acao=acao,
                    alvo_tipo="programa",
                    alvo_id=programa.id,
                    alvo_nome=programa.nome,
                    detalhes={
                        "antes": antes.model_dump(mode="json") if antes else None,
                        "depois": depois.model_dump(mode="json") if depois else None,
                    },
                )
            )
        except Exception:
            # Sem registro, a mudança não fica.
            desfazer()
            raise

    @rotas.get("")
    def listar(
        _autor: Annotated[Usuario, Depends(_exige_editar_programas)],
    ) -> list[ProgramaPublico]:
        return [publico(p) for p in programas.listar()]

    @rotas.post("", status_code=201)
    def criar(
        dados: DadosDoPrograma,
        autor: Annotated[Usuario, Depends(_exige_editar_programas)],
    ) -> ProgramaPublico:
        conferir_pessoas(dados)
        programa = Programa(id=novo_id(), **dados.model_dump())
        gravar(programa)
        registrar(
            "programa.criado",
            autor,
            programa,
            None,
            programa,
            lambda: programas.apagar(programa.id),
        )
        return publico(programa)

    @rotas.put("/{id}")
    def mudar(
        id: str,
        dados: DadosDoPrograma,
        autor: Annotated[Usuario, Depends(_exige_editar_programas)],
    ) -> ProgramaPublico:
        antes = programas.obter(id)
        if antes is None:
            raise HTTPException(404, "Programa inexistente")
        conferir_pessoas(dados)
        depois = Programa(id=id, **dados.model_dump())
        gravar(depois)
        registrar(
            "programa.alterado",
            autor,
            depois,
            antes,
            depois,
            lambda: programas.salvar(antes),
        )
        return publico(depois)

    @rotas.get("/{id}/impacto")
    def impacto(
        id: str, _autor: Annotated[Usuario, Depends(_exige_editar_programas)]
    ) -> ImpactoDoPrograma:
        programa = programas.obter(id)
        if programa is None:
            raise HTTPException(404, "Programa inexistente")
        achados = jobs.consultar(FiltroDeJobs(programa=programa.nome))
        return ImpactoDoPrograma(videos=len(achados.jobs))

    @rotas.delete("/{id}", status_code=204)
    def apagar(
        id: str, autor: Annotated[Usuario, Depends(_exige_editar_programas)]
    ) -> Response:
        antes = programas.obter(id)
        if antes is None:
            raise HTTPException(404, "Programa inexistente")
        try:
            programas.apagar(id)
        except ProgramaInexistente:
            raise HTTPException(404, "Programa inexistente") from None
        registrar(
            "programa.apagado",
            autor,
            antes,
            antes,
            None,
            lambda: programas.salvar(antes),
        )
        return Response(status_code=204)

    @rotas.post("/pessoas", status_code=201)
    def criar_pessoa(
        dados: NovaPessoaDoPrograma,
        autor: Annotated[Usuario, Depends(_exige_editar_programas)],
    ) -> PessoaNoProgramaPublica:
        """A pessoa que ainda não está no catálogo, criada ali mesmo (sem papel: o
        papel é do vínculo com o programa)."""
        existentes = catalogo.achar(dados.nome)
        if existentes:
            pessoa = existentes[0]
        else:
            pessoa = catalogo.acrescentar(
                dados.nome, "", dados.apelidos, autor=autor.email or autor.uid
            )
        return PessoaNoProgramaPublica(
            pessoa_id=pessoa.id, nome=pessoa.nome, apelidos=pessoa.apelidos, papel=""
        )

    return rotas
