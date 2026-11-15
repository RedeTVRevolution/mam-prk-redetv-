"""Quem pode o quê: as dependências de permissão das rotas e as consultas de papel.

Uma rota declara a sua permissão numa linha, `Depends(exige("decupagem.editar", "..."))`.
Um caso novo de permissão nasce aqui, não numa cópia de `isinstance` + 403 dentro da rota.
"""

from collections.abc import Callable

from fastapi import HTTPException, Request

from api.auth import Chamador, ChamadorAutenticado, Escopo, Sistema, Usuario
from api.modelo_do_job import Job
from api.papeis import (
    DocumentoDePapeis,
    Papel,
    Permissao,
    RepositorioDePapeis,
    papeis_do_usuario,
    permissoes_de,
)

# Permissão que a pessoa precisa para cada escopo de chave. Cancelar exige a de enviar.
PERMISSAO_DO_ESCOPO: dict[Escopo, Permissao] = {
    "criar": "video.enviar",
    "ler": "decupagem.ver",
    "cancelar": "video.enviar",
}


def papeis_da_pessoa(request: Request, pessoa: Usuario) -> list[Papel]:
    """Os papéis efetivos, num ponto só para o `/v1/eu` e as rotas nunca discordarem."""
    guardado: DocumentoDePapeis | None = getattr(
        request.state, "papeis_guardados", None
    )
    if guardado is not None and guardado.uid == pessoa.uid:
        # Lido pelo middleware neste pedido; só vale para quem pediu.
        guardados = guardado.papeis
    else:
        papeis: RepositorioDePapeis = request.app.state.papeis
        guardados = papeis.obter(pessoa.uid)
    return papeis_do_usuario(
        guardados,
        pessoa.email,
        pessoa.email_verificado,
        request.app.state.admins,
    )


def tem_permissao(request: Request, pessoa: Usuario, permissao: Permissao) -> bool:
    return permissao in permissoes_de(papeis_da_pessoa(request, pessoa))


def confere_permissao(request: Request, pessoa: Usuario, permissao: Permissao) -> None:
    """403 se a pessoa não tem a permissão por nenhum dos seus papéis."""
    if not tem_permissao(request, pessoa, permissao):
        raise HTTPException(403, f"Sem a permissão {permissao}")


def exige_pessoa(
    chave_nao: str,
) -> Callable[[ChamadorAutenticado], Usuario]:
    """Dependência: só pessoa; a chave de sistema recebe 403 com `chave_nao`. A permissão,
    se houver, é conferida no corpo da rota (`confere_permissao`)."""

    def verificar(chamador: ChamadorAutenticado) -> Usuario:
        if not isinstance(chamador, Usuario):
            raise HTTPException(403, chave_nao)
        return chamador

    return verificar


def exige(
    permissao: Permissao, chave_nao: str
) -> Callable[[Request, ChamadorAutenticado], Usuario]:
    """Dependência: só pessoa com a permissão; chave de sistema recebe 403 com `chave_nao`."""

    def verificar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
        if not isinstance(chamador, Usuario):
            raise HTTPException(403, chave_nao)
        confere_permissao(request, chamador, permissao)
        return chamador

    return verificar


def exige_uma_de(
    permissao: Permissao, outra: Permissao, chave_nao: str
) -> Callable[[Request, ChamadorAutenticado], Usuario]:
    """Dependência: pessoa com uma das duas; sem nenhuma, 403 com a segunda (`outra`)."""

    def verificar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
        if not isinstance(chamador, Usuario):
            raise HTTPException(403, chave_nao)
        if not tem_permissao(request, chamador, permissao):
            confere_permissao(request, chamador, outra)
        return chamador

    return verificar


def exige_escopo(escopo: Escopo) -> Callable[[Request, ChamadorAutenticado], Chamador]:
    """Dependência: chave sem o escopo, ou pessoa sem a permissão dele, recebe 403."""

    def verificar(request: Request, chamador: ChamadorAutenticado) -> Chamador:
        if isinstance(chamador, Sistema):
            if escopo not in chamador.escopos:
                raise HTTPException(403, f"Chave sem o escopo {escopo}")
            return chamador
        confere_permissao(request, chamador, PERMISSAO_DO_ESCOPO[escopo])
        return chamador

    return verificar


def chave_com_algum(*escopos: Escopo) -> Callable[[ChamadorAutenticado], Chamador]:
    """Dependência: chave sem nenhum dos escopos recebe 403; pessoa passa."""

    def verificar(chamador: ChamadorAutenticado) -> Chamador:
        if isinstance(chamador, Sistema) and not set(escopos) & set(chamador.escopos):
            raise HTTPException(403, f"Chave sem o escopo {' ou '.join(escopos)}")
        return chamador

    return verificar


def de_outro_sistema(chamador: Chamador, job: "Job") -> bool:
    """Se a chave de sistema não enxerga o Job (é de outro sistema ou de uma pessoa)."""
    return isinstance(chamador, Sistema) and job.sistema != chamador.sistema


def enxerga(chamador: Chamador, job: "Job | None") -> "Job":
    """O job, ou 404 se não existe ou é de outro sistema (ou de uma pessoa), para uma chave."""
    if job is None or de_outro_sistema(chamador, job):
        raise HTTPException(404, "Job não encontrado")
    return job
