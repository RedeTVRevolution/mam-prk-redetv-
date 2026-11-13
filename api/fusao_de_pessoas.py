"""Fundir duas pessoas do catálogo numa só (E4, #209), em `/v1/catalogo/pessoas/{origem}/fundir`.

A origem não é apagada: passa a apontar para o destino e sai das buscas, e o destino ganha o
nome e os apelidos dela. A leitura das Decupagens mostra o destino onde havia a origem (veja
`com_pessoas_fundidas`); nada gravado é reescrito. As fotos de rosto da origem saem (LGPD).
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from api.auditoria import RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.catalogo import (
    Catalogo,
    FusaoDaPessoa,
    PessoaDoCatalogo,
    nomes_de_busca,
    prefixo_das_fotos,
)
from api.catalogo_dos_jobs import passar_pessoa_nos_jobs
from api.comparador import normalizar
from api.correcoes import Motivo, RepositorioDeCorrecoes, _sem_controle
from api.jobs import FiltroDeJobs, RepositorioDeJobs, _confere_permissao
from api.leitura_da_decupagem import decupagens_corrigidas
from api.lixeira_do_catalogo import FotosDeReferencia, LeituraDeDecupagens
from api.texto_como_dado import ID_SEGURO, Linha, LinhaDaConsulta


class PedidoDeFusao(BaseModel):
    destino_id: Annotated[str, Linha(64, min_length=1), ID_SEGURO]
    motivo: Motivo

    _sem_controle_no_motivo = field_validator("motivo")(_sem_controle)


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


def _exige_fundir(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `catalogo.fundir`; chave de sistema não mexe no catálogo."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não mexe no catálogo")
    _confere_permissao(request, chamador, "catalogo.fundir")
    return chamador


def criar_rotas_da_fusao(
    pessoas: Catalogo,
    repositorio: RepositorioDeJobs,
    correcoes: RepositorioDeCorrecoes,
    decupagens: LeituraDeDecupagens,
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
        _autor: Annotated[Usuario, Depends(_exige_fundir)],
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
        autor: Annotated[Usuario, Depends(_exige_fundir)],
    ) -> Fundida:
        origem, destino = origem_e_destino(id_da_pessoa, pedido.destino_id)
        videos, aparicoes = contar(origem.id)
        quando = relogio()
        ja_tem = set(nomes_de_busca(destino))
        novos: list[str] = []
        for nome in [origem.nome, *origem.apelidos]:
            if normalizar(nome) not in ja_tem:
                ja_tem.add(normalizar(nome))
                novos.append(nome)
        pessoas.corrigir(destino.id, apelidos=[*destino.apelidos, *novos])
        pessoas.definir_fusao(
            origem.id,
            FusaoDaPessoa(
                destino_id=destino.id,
                em=quando,
                por_uid=autor.uid,
                por_email=autor.email.lower(),
                motivo=pedido.motivo,
            ),
        )
        try:
            auditoria.acrescentar(
                RegistroDeAuditoria(
                    id=uuid.uuid4().hex,
                    quando=quando,
                    uid=autor.uid,
                    email=autor.email,
                    acao="pessoa.fundida",
                    alvo_tipo="pessoa",
                    alvo_id=origem.id,
                    alvo_nome=origem.nome,
                    motivo=pedido.motivo,
                    detalhes={
                        "origem_id": origem.id,
                        "origem_nome": origem.nome,
                        "destino_id": destino.id,
                        "destino_nome": destino.nome,
                        "videos": videos,
                        "aparicoes": aparicoes,
                        "fotos_apagadas": len(origem.rostos),
                    },
                )
            )
        except Exception:
            # Sem registro a fusão não vale: nada foi apagado ainda.
            pessoas.definir_fusao(origem.id, None)
            pessoas.corrigir(destino.id, apelidos=destino.apelidos)
            ao_fundir()
            raise
        # Rosto é dado sensível: as fotos da origem saem, e as do destino ficam.
        for rosto in origem.rostos:
            fotos.apagar(rosto.referencia)
        fotos.apagar_prefixo(prefixo_das_fotos(origem.id))
        pessoas.definir_rostos(origem.id, [])
        passar_pessoa_nos_jobs(repositorio, origem.id, destino.id)
        ao_fundir()
        return Fundida(
            origem_id=origem.id,
            destino_id=destino.id,
            destino_nome=destino.nome,
            videos=videos,
            aparicoes=aparicoes,
        )

    return rotas
