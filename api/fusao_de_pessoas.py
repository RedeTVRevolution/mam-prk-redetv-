"""Fundir duas pessoas do catálogo numa só (E4, #209), em `/v1/catalogo/pessoas/{origem}/fundir`.

A origem não é apagada: passa a apontar para o destino e sai das buscas, e o destino ganha o
nome e os apelidos dela. A leitura das Decupagens mostra o destino onde havia a origem (veja
`api.quem_conta`); nada gravado é reescrito. As fotos de rosto da origem saem (LGPD).
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from api.auditoria import RepositorioDeAuditoria, registro_de_auditoria
from api.auth import Usuario
from api.catalogo import (
    Catalogo,
    FusaoDaPessoa,
    FusaoMudou,
    PessoaDoCatalogo,
    nomes_de_busca,
)
from api.catalogo_dos_jobs import passar_pessoa_nos_jobs
from api.correcoes import Motivo, RepositorioDeCorrecoes, sem_controle
from api.fotos_de_referencia import FotosDeReferencia, apagar_fotos_da_pessoa
from api.leitura_da_decupagem import AbreDecupagem, decupagens_corrigidas
from api.modelo_do_job import FiltroDeJobs, RepositorioDeJobs
from api.permissoes import exige
from api.texto import normalizar
from api.texto_como_dado import ID_SEGURO, Linha, LinhaDaConsulta

log = logging.getLogger(__name__)


class PedidoDeFusao(BaseModel):
    destino_id: Annotated[str, Linha(64, min_length=1), ID_SEGURO]
    motivo: Motivo

    _sem_controle_no_motivo = field_validator("motivo")(sem_controle)


class ImpactoDaFusao(BaseModel):
    origem_nome: str
    destino_nome: str
    # Vídeos (concluídos, fora da lixeira) e aparições na imagem da origem que passam ao destino.
    videos: int
    aparicoes: int
    fotos_apagadas: int


class Fundida(BaseModel):
    origem_id: str
    destino_id: str
    destino_nome: str
    videos: int
    aparicoes: int


class FusaoNaoConcluida(Exception):
    """Nem todos os Jobs trocaram a origem pelo destino; o marcador fica e a retomada repete."""


def destino_vigente(pessoas: Catalogo, destino_id: str) -> str:
    """A pessoa que vale hoje: segue a cadeia de fusões (o destino pode ter sido fundido
    depois) até quem não está fundido. Pára num id que não existe ou que já se viu."""
    vistos = {destino_id}
    while (pessoa := pessoas.obter(destino_id)) and pessoa.fundida:
        destino_id = pessoa.fundida.destino_id
        if destino_id in vistos:
            break
        vistos.add(destino_id)
    return destino_id


def _passar_os_nomes(
    pessoas: Catalogo, origem: PessoaDoCatalogo, destino_id: str
) -> None:
    """O nome e os apelidos da origem viram apelidos do destino; repetir não duplica."""
    destino = pessoas.obter(destino_id)
    if destino is None:
        return
    ja_tem = set(nomes_de_busca(destino))
    novos: list[str] = []
    for nome in [origem.nome, *origem.apelidos]:
        if normalizar(nome) not in ja_tem:
            ja_tem.add(normalizar(nome))
            novos.append(nome)
    if novos:
        pessoas.corrigir(destino.id, apelidos=[*destino.apelidos, *novos])


def _avancar(
    pessoas: Catalogo, origem_id: str, fusao: FusaoDaPessoa, nova: FusaoDaPessoa
) -> None:
    """Grava a fase seguinte só se a fusão ainda é esta. Se outro pedido da mesma fusão
    já avançou, o passo dele vale e este segue (os passos se repetem sem estragar)."""
    try:
        pessoas.definir_fusao(
            origem_id,
            nova,
            se=lambda atual: (
                atual is not None and atual.registro_id == fusao.registro_id
            ),
        )
    except FusaoMudou:
        pass


def concluir_fusao(
    origem: PessoaDoCatalogo,
    fusao: FusaoDaPessoa,
    pessoas: Catalogo,
    repositorio: RepositorioDeJobs,
    fotos: FotosDeReferencia,
    auditoria: RepositorioDeAuditoria,
    ao_fundir: Callable[[], None],
) -> Fundida:
    """Os passos depois de gravada a fusão; cada um se repete sem estragar o outro."""
    detalhes = fusao.registro_detalhes or {}
    destino_id = destino_vigente(pessoas, fusao.destino_id)
    if fusao.fase == "aguardando_auditoria":
        _passar_os_nomes(pessoas, origem, destino_id)
        _gravar_o_registro(auditoria, origem, fusao, detalhes)
        limpando = fusao.model_copy(update={"fase": "limpando"})
        _avancar(pessoas, origem.id, fusao, limpando)
        fusao = limpando
    # Rosto é dado sensível: as fotos da origem saem, e as do destino ficam.
    apagar_fotos_da_pessoa(fotos, pessoas, origem)
    # Os Jobs vão ao destino vigente, não ao gravado (#722): ele pode ter sido fundido depois.
    if not passar_pessoa_nos_jobs(repositorio, origem.id, destino_id):
        raise FusaoNaoConcluida(origem.id)
    ao_fundir()
    _avancar(
        pessoas,
        origem.id,
        fusao,
        fusao.model_copy(
            update={"fase": None, "registro_id": None, "registro_detalhes": None}
        ),
    )
    return Fundida(
        origem_id=origem.id,
        destino_id=fusao.destino_id,
        destino_nome=detalhes.get("destino_nome", ""),
        videos=detalhes.get("videos", 0),
        aparicoes=detalhes.get("aparicoes", 0),
    )


def _gravar_o_registro(
    auditoria: RepositorioDeAuditoria,
    origem: PessoaDoCatalogo,
    fusao: FusaoDaPessoa,
    detalhes: dict[str, Any],
) -> None:
    """O registro só se cria: `existe` reconhece o de uma queda depois de gravar, e o
    erro de criar o mesmo id vale como gravado (outro pedido da mesma fusão chegou antes)."""
    registro_id = fusao.registro_id or ""
    if auditoria.existe(registro_id):
        return
    try:
        auditoria.acrescentar(
            registro_de_auditoria(
                quando=fusao.em,
                quem=Usuario(uid=fusao.por_uid, email=fusao.por_email),
                acao="pessoa.fundida",
                alvo_tipo="pessoa",
                alvo_id=origem.id,
                alvo_nome=origem.nome,
                motivo=fusao.motivo,
                detalhes=detalhes,
                id=fusao.registro_id,
            )
        )
    except Exception:
        if not auditoria.existe(registro_id):
            raise


def retomar_fusoes_pendentes(
    pessoas: Catalogo,
    repositorio: RepositorioDeJobs,
    fotos: FotosDeReferencia,
    auditoria: RepositorioDeAuditoria,
    ao_fundir: Callable[[], None],
) -> int:
    """A varredura diária conclui as fusões pendentes, nas duas fases; devolve quantas.
    Uma que falha fica como está e não impede as outras: a próxima varredura tenta."""
    concluidas = 0
    for origem in pessoas.fusoes_pendentes():
        if origem.fundida is None or origem.fundida.fase is None:
            continue
        try:
            concluir_fusao(
                origem,
                origem.fundida,
                pessoas,
                repositorio,
                fotos,
                auditoria,
                ao_fundir,
            )
        except Exception:
            log.exception("a retomada da fusão de %s falhou", origem.id)
            continue
        concluidas += 1
    return concluidas


def criar_rotas_da_fusao(
    pessoas: Catalogo,
    repositorio: RepositorioDeJobs,
    correcoes: RepositorioDeCorrecoes,
    decupagens: AbreDecupagem,
    fotos: FotosDeReferencia,
    auditoria: RepositorioDeAuditoria,
    relogio: Callable[[], datetime],
    ao_fundir: Callable[[], None],
) -> APIRouter:
    rotas = APIRouter()

    def origem_e_destino(
        origem_id: str, destino_id: str
    ) -> tuple[PessoaDoCatalogo, PessoaDoCatalogo]:
        origem = pessoas.obter(origem_id)
        if origem is None:
            raise HTTPException(404, "Pessoa não encontrada")
        if origem.lixeira is not None or origem.fundida is not None:
            raise HTTPException(
                422, "Esta pessoa está na lixeira ou já foi fundida em outra"
            )
        if destino_id == origem_id:
            raise HTTPException(422, "Não dá para fundir uma pessoa nela mesma")
        destino = pessoas.obter(destino_id)
        if destino is None:
            raise HTTPException(422, "A pessoa de destino não existe no catálogo")
        if destino.fundida is not None:
            raise HTTPException(
                422, "A pessoa de destino já foi fundida em outra: escolha a outra"
            )
        if destino.lixeira is not None:
            raise HTTPException(422, "A pessoa de destino está na lixeira")
        return origem, destino

    def contar(origem_id: str) -> tuple[int, int]:
        """Vídeos e aparições que a origem leva, inclusive os de quem já foi fundido nela."""
        videos = aparicoes = 0
        for decupagem in decupagens_corrigidas(
            repositorio,
            correcoes,
            decupagens,
            pessoas,
            FiltroDeJobs(pessoa_do_catalogo=origem_id),
        ):
            nelas = [
                p
                for p in decupagem.get("pessoas") or []
                if isinstance(p, dict) and p.get("catalogo_id") == origem_id
            ]
            videos += bool(nelas)
            aparicoes += sum(len(p.get("na_imagem") or []) for p in nelas)
        return videos, aparicoes

    @rotas.get("/pessoas/{id_da_pessoa}/fundir/impacto")
    def impacto(
        id_da_pessoa: str,
        destino_id: Annotated[str, LinhaDaConsulta(64, min_length=1)],
        _autor: Annotated[
            Usuario,
            Depends(exige("catalogo.fundir", "Chave de sistema não mexe no catálogo")),
        ],
    ) -> ImpactoDaFusao:
        origem, destino = origem_e_destino(id_da_pessoa, destino_id)
        videos, aparicoes = contar(origem.id)
        return ImpactoDaFusao(
            origem_nome=origem.nome,
            destino_nome=destino.nome,
            videos=videos,
            aparicoes=aparicoes,
            fotos_apagadas=len(origem.rostos),
        )

    @rotas.post("/pessoas/{id_da_pessoa}/fundir")
    def fundir(
        id_da_pessoa: str,
        pedido: PedidoDeFusao,
        autor: Annotated[
            Usuario,
            Depends(exige("catalogo.fundir", "Chave de sistema não mexe no catálogo")),
        ],
    ) -> Fundida:
        origem = pessoas.obter(id_da_pessoa)
        fusao = origem.fundida if origem else None
        if origem and fusao and fusao.fase and fusao.destino_id == pedido.destino_id:
            return concluir(
                origem, fusao
            )  # o mesmo pedido de uma fusão que ficou pela metade
        origem, destino = origem_e_destino(id_da_pessoa, pedido.destino_id)
        videos, aparicoes = contar(origem.id)
        quando = relogio()
        ao_fundir()  # antes da mudança: se falha, nada muda (e de novo depois, no fim)
        # A fusão grava com o conteúdo do registro e o marcador: se algo cai daqui até o fim,
        # o mesmo pedido conclui (a leitura já troca a origem pelo destino, e a contagem
        # refeita daria zero). Apagar as fotos antes de gravar apagaria dado biométrico sem registro.
        fusao = FusaoDaPessoa(
            destino_id=destino.id,
            em=quando,
            por_uid=autor.uid,
            por_email=autor.email.lower(),
            motivo=pedido.motivo,
            fase="aguardando_auditoria",
            registro_id=uuid.uuid4().hex,
            registro_detalhes={
                "origem_id": origem.id,
                "origem_nome": origem.nome,
                "destino_id": destino.id,
                "destino_nome": destino.nome,
                "videos": videos,
                "aparicoes": aparicoes,
                "fotos_apagadas": len(origem.rostos),
            },
        )
        try:
            # Só se ninguém fundiu a origem desde a validação (outro pedido ao mesmo tempo).
            pessoas.definir_fusao(origem.id, fusao, se=lambda atual: atual is None)
        except FusaoMudou:
            raise HTTPException(
                409, "Esta pessoa acabou de ser fundida em outra: recarregue"
            ) from None
        return concluir(origem, fusao)

    def concluir(origem: PessoaDoCatalogo, fusao: FusaoDaPessoa) -> Fundida:
        try:
            return concluir_fusao(
                origem, fusao, pessoas, repositorio, fotos, auditoria, ao_fundir
            )
        except FusaoNaoConcluida:
            raise HTTPException(
                500, "Nem todos os vídeos passaram: repita o pedido"
            ) from None

    return rotas
