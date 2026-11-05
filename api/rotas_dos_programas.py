"""Rotas da aba Programas da administração (#338).

Quem tem `programas.editar` (Editor, Curador e Administrador) cria, edita e apaga
programas, inclui pessoas do catálogo com o papel que têm no programa e cria a
pessoa que ainda não existe. Toda mudança vai para a auditoria; se o registro não
for gravado, a mudança é desfeita.

O Job guarda o nome do programa: renomear troca o nome nos vídeos (inclusive os da
lixeira, que podem voltar) e os reindexa (busca e cópia no BigQuery) em segundo plano,
com o andamento gravado no programa, como na renomeação de pessoa; `retomar` continua de
onde parou. Só a tarefa grava o andamento depois de criado, e só ele: as outras gravações
do programa não o tocam.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel, StringConstraints, field_validator

from api.auditoria import Acao, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.catalogo import Catalogo, visivel
from api.correcoes import _sem_controle
from api.jobs import FiltroDeJobs, Job, RepositorioDeJobs, _confere_permissao
from api.programas import (
    NomeDoPrograma,
    NomeEmUso,
    PerfilEmTexto,
    Programa,
    ProgramaInexistente,
    RenomeacaoDoPrograma,
    RepositorioDeProgramas,
    VinculoDaPessoa,
    novo_id,
)
from api.renomeacao_de_pessoas import RODADAS, AndamentoDaRenomeacao

log = logging.getLogger(__name__)

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
    renomeacao: AndamentoDaRenomeacao | None = None


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
    reindexar: Callable[[Job], bool],
    ao_criar_pessoa: Callable[[], None],
) -> APIRouter:
    """`reindexar` devolve se o vídeo ficou no índice e na cópia; `ao_criar_pessoa`
    descarta a cópia da lista de pessoas."""
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
        r = programa.renomeacao
        return ProgramaPublico(
            id=programa.id,
            nome=programa.nome,
            perfil=programa.perfil,
            pessoas=pessoas,
            renomeacao=None
            if r is None
            else AndamentoDaRenomeacao(
                estado=r.estado,
                feitos=r.total - len(r.pendentes),
                total=r.total,
                nome_antigo=r.nome_antigo,
                nome_novo=r.nome_novo,
            ),
        )

    def conferir_pessoas(dados: DadosDoPrograma) -> None:
        for v in dados.pessoas:
            pessoa = catalogo.obter(v.pessoa_id)
            if pessoa is None or not visivel(pessoa):
                raise HTTPException(422, f"Pessoa fora do catálogo: {v.pessoa_id}")

    def gravar(programa: Programa, com_renomeacao: bool = False) -> None:
        try:
            programas.salvar(programa, com_renomeacao=com_renomeacao)
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
        sem = {"renomeacao"}
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
                    # Sem o andamento da troca de nome: a lista de pendentes é longa.
                    detalhes={
                        "antes": antes.model_dump(mode="json", exclude=sem)
                        if antes
                        else None,
                        "depois": depois.model_dump(mode="json", exclude=sem)
                        if depois
                        else None,
                    },
                )
            )
        except Exception:
            # Sem registro, a mudança não fica.
            desfazer()
            raise

    def definir_renomeacao(
        programa_id: str,
        mudar: Callable[[RenomeacaoDoPrograma], RenomeacaoDoPrograma],
    ) -> RenomeacaoDoPrograma | None:
        """Muda só o andamento, lido de novo; `None` se o programa ou a troca sumiram."""
        programa = programas.obter(programa_id)
        if programa is None or programa.renomeacao is None:
            return None
        r = mudar(programa.renomeacao)
        try:
            programas.gravar_renomeacao(programa_id, r)
        except ProgramaInexistente:
            return None
        return r

    def tirar_pendente(programa_id: str, job_id: str) -> RenomeacaoDoPrograma | None:
        return definir_renomeacao(
            programa_id,
            lambda r: r.model_copy(
                update={"pendentes": [i for i in r.pendentes if i != job_id]}
            ),
        )

    # Programas com a troca rodando nesta instância: `retomar` não abre uma segunda.
    em_execucao: set[str] = set()

    def religar_videos(programa_id: str) -> None:
        """Troca o nome nos vídeos pendentes e os reindexa, em até `RODADAS` rodadas."""
        if programa_id in em_execucao:
            return
        em_execucao.add(programa_id)
        try:
            _religar_videos(programa_id)
        finally:
            em_execucao.discard(programa_id)

    def _religar_videos(programa_id: str) -> None:
        r = definir_renomeacao(
            programa_id, lambda r: r.model_copy(update={"estado": "em_andamento"})
        )
        if r is None:
            return
        para = r.nome_novo
        for _ in range(RODADAS):
            for job_id in list(r.pendentes):
                try:
                    # Reindexa o Job devolvido pela troca (ou relido, se a troca já
                    # tinha sido feita), nunca um lido antes: ele levaria o nome antigo.
                    # O pendente herdado de uma troca que falhou pode ter um nome mais
                    # antigo que `nome_antigo`: vale todo nome que não é o novo.
                    job = jobs.trocar(
                        job_id,
                        lambda j: {"programa": para} if j.programa != para else None,
                    ) or jobs.obter(job_id)
                    # Na lixeira também: restaurar não reindexa, e o vídeo voltaria
                    # com o nome antigo na busca e nos relatórios.
                    pronto = job is None or job.estado != "concluido" or reindexar(job)
                    if pronto and tirar_pendente(programa_id, job_id) is None:
                        return  # o programa foi apagado
                except Exception:
                    # O Job fica pendente; a tarefa segue e `retomar` o tenta de novo.
                    log.exception("troca do programa em %s falhou", job_id)
            programa = programas.obter(programa_id)
            if programa is None or programa.renomeacao is None:
                return
            r = programa.renomeacao
            if not r.pendentes:
                break
        definir_renomeacao(
            programa_id,
            lambda r: r.model_copy(
                update={"estado": "falhou" if r.pendentes else "concluida"}
            ),
        )

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
        segundo_plano: BackgroundTasks,
        autor: Annotated[Usuario, Depends(_exige_editar_programas)],
    ) -> ProgramaPublico:
        antes = programas.obter(id)
        if antes is None:
            raise HTTPException(404, "Programa inexistente")
        renomear = antes.nome != dados.nome
        anterior = antes.renomeacao
        if renomear and anterior is not None and anterior.estado == "em_andamento":
            raise HTTPException(
                409, "A troca de nome anterior ainda não terminou: aguarde ou retome"
            )
        conferir_pessoas(dados)
        depois = Programa(id=id, **dados.model_dump(), renomeacao=anterior)
        if renomear:
            # Antes de gravar: todos os vídeos com o nome antigo, inclusive os da
            # lixeira, mais os que a troca que falhou deixou pendentes.
            herdados = anterior.pendentes if anterior is not None else []
            achados = jobs.consultar(FiltroDeJobs(programa=antes.nome, na_lixeira=None))
            ids = list(dict.fromkeys([*herdados, *(j.id for j in achados.jobs)]))
            depois.renomeacao = RenomeacaoDoPrograma(
                nome_antigo=antes.nome,
                nome_novo=depois.nome,
                total=len(ids),
                pendentes=ids,
                estado="em_andamento",
            )
        # Nome e andamento numa gravação só; sem troca de nome, o andamento não muda.
        gravar(depois, com_renomeacao=renomear)
        registrar(
            "programa.alterado",
            autor,
            depois,
            antes,
            depois,
            lambda: programas.salvar(antes, com_renomeacao=renomear),
        )
        if renomear:
            segundo_plano.add_task(religar_videos, id)
        return publico(depois)

    @rotas.post("/{id}/renomear/retomar")
    def retomar(
        id: str,
        segundo_plano: BackgroundTasks,
        _autor: Annotated[Usuario, Depends(_exige_editar_programas)],
    ) -> ProgramaPublico:
        programa = programas.obter(id)
        if programa is None or programa.renomeacao is None:
            raise HTTPException(404, "Nenhuma troca de nome deste programa")
        if programa.renomeacao.estado != "concluida":
            segundo_plano.add_task(religar_videos, id)
        return publico(programa)

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
        if antes.renomeacao is not None and antes.renomeacao.estado == "em_andamento":
            raise HTTPException(409, "A troca de nome ainda não terminou: aguarde")
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
            lambda: programas.salvar(antes, com_renomeacao=True),
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
                dados.nome,
                "",
                dados.apelidos,
                a_revisar=True,
                autor=autor.email or autor.uid,
            )
            ao_criar_pessoa()
        return PessoaNoProgramaPublica(
            pessoa_id=pessoa.id, nome=pessoa.nome, apelidos=pessoa.apelidos, papel=""
        )

    return rotas
