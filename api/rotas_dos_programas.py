"""Rotas da aba Programas da administração (#338).

Quem tem `programas.editar` (Editor, Curador e Administrador) cria, edita e apaga
programas, inclui pessoas do catálogo com o papel que têm no programa e cria a
pessoa que ainda não existe. Toda mudança vai para a auditoria; se o registro não
for gravado, a mudança é desfeita.

O Job guarda o nome do programa: renomear troca o nome nos vídeos (inclusive os da
lixeira, que podem voltar) e os reindexa (busca e cópia no BigQuery) em segundo plano,
com o andamento gravado no programa, como na renomeação de pessoa; `retomar` continua de
onde parou. O andamento só muda por `trocar` (transação), conferindo que ainda é o da
mesma troca e no estado lido; as outras gravações do programa não o tocam.

A troca nasce `confirmando`, junto com o nome, e só passa a `em_andamento` (e mexe nos
vídeos) depois da auditoria gravada: se a auditoria falha, o desfazer não deixa vídeo com
o nome novo.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
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
    TrocaSubstituida,
    VinculoDaPessoa,
    novo_id,
    pessoas_do_programa,
    troca_vale,
)
from api.renomeacao_de_pessoas import RODADAS, AndamentoDaRenomeacao

log = logging.getLogger(__name__)

LIMITE_DE_APELIDOS = 20
LIMITE_DO_APELIDO = 100
LIMITE_DE_PESSOAS_NO_PROGRAMA = 200
# Uma troca `confirmando` mais velha que isto é de um PUT que morreu entre gravar e
# auditar: o serviço web não passa do tempo padrão do Cloud Run (300 s), com folga.
PRAZO_DA_CONFIRMACAO = timedelta(minutes=15)
EM_CURSO = ("confirmando", "em_andamento")

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
        visiveis, _ = pessoas_do_programa(programa, catalogo)
        pessoas = [
            PessoaNoProgramaPublica(
                pessoa_id=pessoa.id,
                nome=pessoa.nome,
                apelidos=pessoa.apelidos,
                papel=papel,
            )
            for pessoa, papel in visiveis
        ]
        r = programa.renomeacao
        return ProgramaPublico(
            id=programa.id,
            nome=programa.nome,
            perfil=programa.perfil,
            pessoas=pessoas,
            renomeacao=None
            if r is None
            else AndamentoDaRenomeacao(
                # Para quem lê, a troca que espera a auditoria já está em andamento.
                estado="em_andamento" if r.estado == "confirmando" else r.estado,
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
        desfazer: Callable[[], object],
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

    def mudar_a_troca(
        programa_id: str,
        troca_id: str,
        de: tuple[str, ...],
        mudar: Callable[[RenomeacaoDoPrograma], RenomeacaoDoPrograma],
    ) -> RenomeacaoDoPrograma | None:
        """Muda o andamento numa transação, só se ainda é o da troca `troca_id` e está num
        dos estados `de`; `None` se não é mais (outra troca, outro estado, programa apagado)."""

        def condicional(p: Programa) -> Programa | None:
            r = p.renomeacao
            if r is None or r.id != troca_id or r.estado not in de:
                return None
            return p.model_copy(update={"renomeacao": mudar(r)})

        gravado = programas.trocar(programa_id, condicional)
        return gravado.renomeacao if gravado else None

    def da_troca(programa_id: str, troca_id: str) -> RenomeacaoDoPrograma | None:
        """O andamento, se ainda é o da troca `troca_id` e está em andamento."""
        programa = programas.obter(programa_id)
        return (
            programa.renomeacao if programa and troca_vale(programa, troca_id) else None
        )

    def tirar_pendente(
        programa_id: str, troca_id: str, job_id: str
    ) -> RenomeacaoDoPrograma | None:
        return mudar_a_troca(
            programa_id,
            troca_id,
            ("em_andamento",),
            lambda r: r.model_copy(
                update={"pendentes": [i for i in r.pendentes if i != job_id]}
            ),
        )

    # Trocas rodando nesta instância: `retomar` não abre uma segunda da mesma.
    em_execucao: set[str] = set()

    def religar_videos(programa_id: str, troca_id: str) -> None:
        """Troca o nome nos vídeos pendentes e os reindexa, em até `RODADAS` rodadas."""
        if troca_id in em_execucao:
            return
        em_execucao.add(troca_id)
        try:
            _religar_videos(programa_id, troca_id)
        finally:
            em_execucao.discard(troca_id)

    def _religar_videos(programa_id: str, troca_id: str) -> None:
        r = da_troca(programa_id, troca_id)
        if r is None:
            return
        for _ in range(RODADAS):
            for job_id in list(r.pendentes):
                try:
                    # Antes de mexer no Job: outra troca pode ter tomado o lugar desta.
                    if da_troca(programa_id, troca_id) is None:
                        return
                    # O Job recebe o nome do programa só se esta troca ainda está em
                    # andamento, conferido na mesma transação: entre a conferência
                    # acima e a gravação, outra instância pode ter terminado esta troca
                    # e começado outra. Também leva ao nome atual o pendente herdado
                    # com um nome mais antigo. Reindexa o Job devolvido, nunca um lido
                    # antes.
                    job = programas.levar_o_nome_ao_job(
                        programa_id, troca_id, job_id, jobs
                    )
                    # Na lixeira também: restaurar não reindexa, e o vídeo voltaria
                    # com o nome antigo na busca e nos relatórios.
                    pronto = job is None or job.estado != "concluido" or reindexar(job)
                    if pronto and tirar_pendente(programa_id, troca_id, job_id) is None:
                        return  # outra troca, ou o programa foi apagado
                except TrocaSubstituida:
                    # Sem tirar pendente nem fechar a troca: ela não é mais desta tarefa.
                    return
                except Exception:
                    # O Job fica pendente; a tarefa segue e `retomar` o tenta de novo.
                    log.exception("troca do programa em %s falhou", job_id)
            r = da_troca(programa_id, troca_id)
            if r is None:
                return
            if not r.pendentes:
                break
        mudar_a_troca(
            programa_id,
            troca_id,
            ("em_andamento",),
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
        anterior = antes.renomeacao
        conferir_pessoas(dados)
        depois = Programa(id=id, **dados.model_dump(), renomeacao=anterior)
        # A tela só vê as pessoas visíveis: o vínculo com quem está na lixeira não sai
        # no salvar (restaurar a pessoa o devolve, com o mesmo papel).
        _, escondidos = pessoas_do_programa(antes, catalogo)
        depois.pessoas = [*depois.pessoas, *escondidos]
        if antes.nome == dados.nome:
            # Sem troca de nome, o andamento não muda.
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
        if anterior is not None and anterior.estado in EM_CURSO:
            raise HTTPException(
                409, "A troca de nome anterior ainda não terminou: aguarde ou retome"
            )
        # Antes de gravar: todos os vídeos com o nome antigo, inclusive os da lixeira,
        # mais os que a troca que falhou deixou pendentes.
        herdados = anterior.pendentes if anterior is not None else []
        achados = jobs.consultar(FiltroDeJobs(programa=antes.nome, na_lixeira=None))
        ids = list(dict.fromkeys([*herdados, *(j.id for j in achados.jobs)]))
        nova = RenomeacaoDoPrograma(
            id=uuid.uuid4().hex,
            nome_antigo=antes.nome,
            nome_novo=depois.nome,
            total=len(ids),
            pendentes=ids,
            estado="confirmando",
            desde=relogio(),
        )
        depois.renomeacao = nova

        def mesma_troca(r: RenomeacaoDoPrograma | None) -> bool:
            if r is None or anterior is None:
                return r is anterior
            return (r.id, r.estado) == (anterior.id, anterior.estado)

        # Nome e andamento numa gravação só, se nada mudou desde a leitura: um `retomar`
        # no meio já começou a troca antiga.
        try:
            gravado = programas.trocar(
                id,
                lambda p: (
                    depois
                    if p.nome == antes.nome and mesma_troca(p.renomeacao)
                    else None
                ),
            )
        except NomeEmUso:
            raise HTTPException(409, "Já existe um programa com esse nome") from None
        if gravado is None:
            raise HTTPException(409, "O programa mudou enquanto isso: tente de novo")
        registrar(
            "programa.alterado",
            autor,
            depois,
            antes,
            depois,
            # Só enquanto a troca espera: se um `retomar` depois do prazo já a
            # começou, desfazer deixaria vídeos com o nome novo.
            lambda: programas.trocar(
                id,
                lambda p: (
                    antes
                    if p.renomeacao is not None
                    and (p.renomeacao.id, p.renomeacao.estado)
                    == (nova.id, "confirmando")
                    else None
                ),
            ),
        )
        # Só com a auditoria gravada a troca mexe nos vídeos.
        if mudar_a_troca(
            id,
            nova.id,
            ("confirmando",),
            lambda r: r.model_copy(update={"estado": "em_andamento"}),
        ):
            segundo_plano.add_task(religar_videos, id, nova.id)
        return publico(depois)

    @rotas.post("/{id}/renomear/retomar")
    def retomar(
        id: str,
        segundo_plano: BackgroundTasks,
        autor: Annotated[Usuario, Depends(_exige_editar_programas)],
    ) -> ProgramaPublico:
        programa = programas.obter(id)
        if programa is None or programa.renomeacao is None:
            raise HTTPException(404, "Nenhuma troca de nome deste programa")
        r = programa.renomeacao
        if r.estado == "concluida":
            return publico(programa)
        if r.estado == "confirmando":
            if r.desde is None or relogio() - r.desde < PRAZO_DA_CONFIRMACAO:
                raise HTTPException(409, "A troca de nome ainda espera a auditoria")
            # O PUT morreu entre gravar e auditar. O nome novo já vale para todos e não
            # se sabe se a auditoria chegou a gravar: quem retoma registra a mudança
            # (talvez em dobro) e a troca segue; sem o registro, não segue.
            log.warning("troca %s do programa %s retomada sem confirmar", r.id, id)
            try:
                auditoria.acrescentar(
                    RegistroDeAuditoria(
                        id=uuid.uuid4().hex,
                        quando=relogio(),
                        uid=autor.uid,
                        email=autor.email,
                        acao="programa.alterado",
                        alvo_tipo="programa",
                        alvo_id=id,
                        alvo_nome=programa.nome,
                        detalhes={
                            "recuperacao": "troca de nome vencida, sem confirmar",
                            "troca": r.id,
                            "nome_antigo": r.nome_antigo,
                            "nome_novo": r.nome_novo,
                        },
                    )
                )
            except Exception:
                log.exception("auditoria da troca %s retomada falhou", r.id)
                raise HTTPException(
                    503, "Auditoria indisponível: tente de novo"
                ) from None
        retomada = mudar_a_troca(
            id,
            r.id,
            (r.estado,),
            lambda r: r.model_copy(update={"estado": "em_andamento"}),
        )
        if retomada is None:
            raise HTTPException(
                409, "A troca de nome mudou enquanto isso: tente de novo"
            )
        segundo_plano.add_task(religar_videos, id, r.id)
        return publico(programa.model_copy(update={"renomeacao": retomada}))

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
        if antes.renomeacao is not None and antes.renomeacao.estado in EM_CURSO:
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
