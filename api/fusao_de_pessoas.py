"""Fundir duas pessoas do catálogo numa só (E4, #209), em `/v1/catalogo/pessoas/{origem}/fundir`.

A origem não é apagada: passa a apontar para o destino e sai das buscas, e o destino ganha o
nome e os apelidos dela. A leitura das Decupagens mostra o destino onde havia a origem (veja
`api.quem_conta`); nada gravado é reescrito. As fotos de rosto da origem saem (LGPD).
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from api.auditoria import RepositorioDeAuditoria, registro_de_auditoria
from api.auth import Usuario
from api.catalogo import (
    Catalogo,
    FusaoDaPessoa,
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
        ja_tem = set(nomes_de_busca(destino))
        novos: list[str] = []
        for nome in [origem.nome, *origem.apelidos]:
            if normalizar(nome) not in ja_tem:
                ja_tem.add(normalizar(nome))
                novos.append(nome)
        pessoas.corrigir(destino.id, apelidos=[*destino.apelidos, *novos])
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
        pessoas.definir_fusao(origem.id, fusao)
        return concluir(origem, fusao)

    def concluir(origem: PessoaDoCatalogo, fusao: FusaoDaPessoa) -> Fundida:
        """Os passos depois de gravada a fusão; cada um se repete sem estragar o outro."""
        detalhes = fusao.registro_detalhes or {}
        if fusao.fase == "aguardando_auditoria":
            # `existe`: a queda pode ter vindo depois de gravar o registro (que só se cria).
            if not auditoria.existe(fusao.registro_id or ""):
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
            fusao = fusao.model_copy(update={"fase": "limpando"})
            pessoas.definir_fusao(origem.id, fusao)
        # Rosto é dado sensível: as fotos da origem saem, e as do destino ficam.
        apagar_fotos_da_pessoa(fotos, pessoas, origem)
        if not passar_pessoa_nos_jobs(repositorio, origem.id, fusao.destino_id):
            raise HTTPException(500, "Nem todos os vídeos passaram: repita o pedido")
        ao_fundir()
        pessoas.definir_fusao(
            origem.id,
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

    return rotas
