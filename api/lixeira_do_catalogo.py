"""Lixeira das pessoas e marcas do catálogo (E8, #151), em `/v1/admin/lixeira`.

Mandar para a lixeira é do Curador e do Administrador (`catalogo.apagar`); restaurar e
purgar, só do Administrador (`lixeira.gerir`). A pessoa perde já as fotos de rosto (LGPD) e,
na leitura das Decupagens, o nome que só o rosto sustentava; a marca perde o vínculo com o
catálogo e mantém o texto. A saída do modelo não é tocada (ADR 0010).
"""

import json
import logging
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from api.auditoria import Acao, RegistroDeAuditoria, RepositorioDeAuditoria
from api.auth import ChamadorAutenticado, Usuario
from api.catalogo import (
    Catalogo,
    EnvioParaLixeira,
    PessoaInexistente,
    prefixo_das_fotos,
)
from api.catalogo_apagado import so_o_rosto
from api.correcoes import (
    RepositorioDeCorrecoes,
    decupagem_entregue,
    versao_do_modelo,
)
from api.jobs import FiltroDeJobs, Job, RepositorioDeJobs, _confere_permissao
from api.lixeira import (
    PRAZO_DA_PURGA,
    Envio,
    ItemDaLixeira,
    _exige_gerir,
    item_da_lixeira,
    login_recente_ou_403,
)
from api.marcas import CatalogoDeMarcas, MarcaInexistente

log = logging.getLogger(__name__)

SISTEMA_DA_PURGA = "Purga automática"


class FotosDeReferencia(Protocol):
    """Porta para o bucket das referências; os testes usam a versão em memória."""

    def apagar(self, objeto: str) -> None: ...

    def apagar_prefixo(self, prefixo: str) -> None: ...


class FotosEmMemoria:
    def __init__(self, objetos: set[str] | None = None) -> None:
        self.objetos = objetos if objetos is not None else set()

    def apagar(self, objeto: str) -> None:
        self.objetos.discard(objeto)

    def apagar_prefixo(self, prefixo: str) -> None:
        self.objetos = {o for o in self.objetos if not o.startswith(prefixo)}


class LeituraDeDecupagens(Protocol):
    def abrir_decupagem(self, job_id: str) -> Iterator[bytes]: ...


class ImpactoDaPessoa(BaseModel):
    aparicoes_que_perdem_o_nome: int
    fotos_apagadas: int
    # Restaurar devolve a pessoa ao catálogo, mas não as fotos.
    restaurar_devolve_as_fotos: bool = False


class ImpactoDaMarca(BaseModel):
    ocorrencias_que_perdem_o_vinculo: int


def _exige_apagar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `catalogo.apagar`; chave de sistema não mexe no catálogo."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não mexe no catálogo")
    _confere_permissao(request, chamador, "catalogo.apagar")
    return chamador


class PedidoDePurga(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # O nome, digitado: a prova de que a pessoa sabe o que está apagando.
    nome: str


class Restaurado(BaseModel):
    id: str
    nome: str


def _registro(
    tipo: Literal["pessoa", "marca"],
    acao: Acao,
    id: str,
    nome: str,
    motivo: str,
    detalhes: dict[str, Any],
    quando: datetime,
    autor: Usuario | None,
) -> RegistroDeAuditoria:
    return RegistroDeAuditoria(
        id=uuid.uuid4().hex,
        quando=quando,
        uid=autor.uid if autor else None,
        email=autor.email if autor else None,
        sistema=None if autor else SISTEMA_DA_PURGA,
        acao=acao,
        alvo_tipo=tipo,
        alvo_id=id,
        alvo_nome=nome,
        motivo=motivo,
        detalhes=detalhes,
    )


def purgar_catalogo_vencido(
    pessoas: Catalogo,
    marcas: CatalogoDeMarcas,
    auditoria: RepositorioDeAuditoria,
    agora: datetime,
) -> int:
    """Purga as pessoas e marcas na lixeira há `PRAZO_DA_PURGA` ou mais; devolve quantas.
    Cada uma grava o registro antes de sair; a que falha fica e a próxima execução tenta."""
    purgadas = 0
    itens: list[tuple[Literal["pessoa", "marca"], str, str, EnvioParaLixeira]] = [
        ("pessoa", p.id, p.nome, p.lixeira) for p in pessoas.na_lixeira() if p.lixeira
    ] + [("marca", m.id, m.nome, m.lixeira) for m in marcas.na_lixeira() if m.lixeira]
    for tipo, id, nome, envio in itens:
        if agora - envio.em < PRAZO_DA_PURGA:
            continue
        try:
            auditoria.acrescentar(
                _registro(tipo, "item.purgado", id, nome, envio.motivo, {}, agora, None)
            )
            (pessoas if tipo == "pessoa" else marcas).apagar(id)
        except Exception:
            log.exception("a purga de %s %s falhou", tipo, id)
            continue
        purgadas += 1
    return purgadas


def decupagens_dos_jobs(
    repositorio: RepositorioDeJobs,
    correcoes: RepositorioDeCorrecoes,
    decupagens: LeituraDeDecupagens,
    filtro: FiltroDeJobs | None = None,
) -> Iterator[tuple[Job, dict[str, Any]]]:
    """Cada vídeo concluído fora da lixeira (e que casa com `filtro`) com a Decupagem
    entregue; a que não lê é pulada."""
    for job in repositorio.consultar(filtro or FiltroDeJobs()).jobs:
        if job.estado != "concluido":
            continue
        try:
            conteudo = b"".join(decupagens.abrir_decupagem(job.id))
            entregue = decupagem_entregue(
                json.loads(conteudo),
                versao_do_modelo(conteudo),
                correcoes.listar(job.id),
            )
        except Exception:  # noqa: BLE001 - uma Decupagem ruim não trava o impacto
            log.warning("decupagem de %s não lida; fora do impacto", job.id)
            continue
        yield job, entregue


def decupagens_entregues(
    repositorio: RepositorioDeJobs,
    correcoes: RepositorioDeCorrecoes,
    decupagens: LeituraDeDecupagens,
    filtro: FiltroDeJobs | None = None,
) -> Iterator[dict[str, Any]]:
    """A Decupagem entregue de cada vídeo concluído fora da lixeira; a que não lê é pulada."""
    for _job, entregue in decupagens_dos_jobs(
        repositorio, correcoes, decupagens, filtro
    ):
        yield entregue


def criar_rotas_da_lixeira_do_catalogo(
    pessoas: Catalogo,
    marcas: CatalogoDeMarcas,
    repositorio: RepositorioDeJobs,
    correcoes: RepositorioDeCorrecoes,
    decupagens: LeituraDeDecupagens,
    fotos: FotosDeReferencia,
    auditoria: RepositorioDeAuditoria,
    relogio: Callable[[], datetime],
    login_recente: timedelta,
    descartar_pessoas: Callable[[], None] = lambda: None,
) -> APIRouter:
    """`descartar_pessoas` descarta a cópia curta das pessoas (#364): quem entra na
    lixeira ou sai dela muda o autocompletar e a grafia aproximada da busca na hora."""
    rotas = APIRouter(prefix="/admin/lixeira")

    def lixeira_da_pessoa(id: str, envio: EnvioParaLixeira | None) -> None:
        pessoas.definir_lixeira(id, envio)
        descartar_pessoas()

    def entregues(filtro: FiltroDeJobs) -> Iterator[dict[str, Any]]:
        return decupagens_entregues(repositorio, correcoes, decupagens, filtro)

    def impacto_da_pessoa(id: str, fotos_dela: int) -> ImpactoDaPessoa:
        aparicoes = sum(
            len(p.get("na_imagem") or [])
            for d in entregues(FiltroDeJobs(pessoa_do_catalogo=id))
            for p in d.get("pessoas") or []
            if p.get("catalogo_id") == id and so_o_rosto(p.get("fontes_do_nome") or [])
        )
        return ImpactoDaPessoa(
            aparicoes_que_perdem_o_nome=aparicoes, fotos_apagadas=fotos_dela
        )

    def impacto_da_marca(id: str) -> ImpactoDaMarca:
        return ImpactoDaMarca(
            ocorrencias_que_perdem_o_vinculo=sum(
                1
                for d in entregues(FiltroDeJobs(marca_do_catalogo=id))
                for c in d.get("comerciais") or []
                if c.get("catalogo_id") == id
            )
        )

    def pessoa(id: str) -> Any:
        achada = pessoas.obter(id)
        if achada is None:
            raise HTTPException(404, "Pessoa não encontrada")
        return achada

    def marca(id: str) -> Any:
        achada = marcas.obter(id)
        if achada is None:
            raise HTTPException(404, "Marca não encontrada")
        return achada

    def registrar(
        tipo: Literal["pessoa", "marca"],
        acao: Acao,
        item: Any,
        motivo: str,
        detalhes: dict[str, Any],
        autor: Usuario,
    ) -> None:
        auditoria.acrescentar(
            _registro(
                tipo, acao, item.id, item.nome, motivo, detalhes, relogio(), autor
            )
        )

    def envio_de(autor: Usuario, motivo: str) -> EnvioParaLixeira:
        return EnvioParaLixeira(
            em=relogio(),
            por_uid=autor.uid,
            por_email=autor.email.lower(),
            motivo=motivo,
        )

    @rotas.get("/pessoas/{id_da_pessoa}/impacto")
    def impacto_pessoa(
        id_da_pessoa: str, _autor: Annotated[Usuario, Depends(_exige_apagar)]
    ) -> ImpactoDaPessoa:
        achada = pessoa(id_da_pessoa)
        return impacto_da_pessoa(achada.id, len(achada.rostos))

    @rotas.get("/marcas/{id_da_marca}/impacto")
    def impacto_marca(
        id_da_marca: str, _autor: Annotated[Usuario, Depends(_exige_apagar)]
    ) -> ImpactoDaMarca:
        return impacto_da_marca(marca(id_da_marca).id)

    @rotas.post("/pessoas/{id_da_pessoa}", status_code=201)
    def enviar_pessoa(
        id_da_pessoa: str,
        pedido: Envio,
        autor: Annotated[Usuario, Depends(_exige_apagar)],
    ) -> ItemDaLixeira:
        achada = pessoa(id_da_pessoa)
        if achada.lixeira is not None:
            raise HTTPException(409, "A pessoa já está na lixeira")
        if achada.fundida is not None:
            # Purgada, ela levaria o apontamento: a leitura deixaria de mostrar o destino.
            raise HTTPException(422, "Esta pessoa foi fundida em outra: apague a outra")
        impacto = impacto_da_pessoa(achada.id, len(achada.rostos))
        # Rosto é dado sensível: as fotos saem já, sem esperar a purga, e não voltam.
        # Pela pasta da pessoa também: as fotos da web trocadas antes ficaram lá.
        for rosto in achada.rostos:
            fotos.apagar(rosto.referencia)
        fotos.apagar_prefixo(prefixo_das_fotos(achada.id))
        pessoas.definir_rostos(achada.id, [])
        envio = envio_de(autor, pedido.motivo)
        lixeira_da_pessoa(achada.id, envio)
        try:
            registrar(
                "pessoa",
                "item.para_lixeira",
                achada,
                pedido.motivo,
                impacto.model_dump(),
                autor,
            )
        except Exception:
            # Sem registro a pessoa volta (as fotos, não: já saíram).
            lixeira_da_pessoa(achada.id, None)
            raise
        return item_da_lixeira("pessoa", achada.id, achada.nome, envio, relogio())

    @rotas.post("/marcas/{id_da_marca}", status_code=201)
    def enviar_marca(
        id_da_marca: str,
        pedido: Envio,
        autor: Annotated[Usuario, Depends(_exige_apagar)],
    ) -> ItemDaLixeira:
        achada = marca(id_da_marca)
        if achada.lixeira is not None:
            raise HTTPException(409, "A marca já está na lixeira")
        impacto = impacto_da_marca(achada.id)
        envio = envio_de(autor, pedido.motivo)
        marcas.definir_lixeira(achada.id, envio)
        try:
            registrar(
                "marca",
                "item.para_lixeira",
                achada,
                pedido.motivo,
                impacto.model_dump(),
                autor,
            )
        except Exception:
            marcas.definir_lixeira(achada.id, None)
            raise
        return item_da_lixeira("marca", achada.id, achada.nome, envio, relogio())

    @rotas.post("/pessoas/{id_da_pessoa}/restaurar")
    def restaurar_pessoa(
        id_da_pessoa: str, autor: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> Restaurado:
        achada = pessoa(id_da_pessoa)
        if achada.lixeira is None:
            raise HTTPException(409, "A pessoa não está na lixeira")
        # As fotos já saíram no envio e não voltam: o registro conta 0 delas.
        impacto = impacto_da_pessoa(achada.id, 0)
        lixeira_da_pessoa(achada.id, None)
        try:
            registrar(
                "pessoa",
                "item.restaurado",
                achada,
                achada.lixeira.motivo,
                impacto.model_dump(),
                autor,
            )
        except Exception:
            lixeira_da_pessoa(achada.id, achada.lixeira)
            raise
        return Restaurado(id=achada.id, nome=achada.nome)

    @rotas.post("/marcas/{id_da_marca}/restaurar")
    def restaurar_marca(
        id_da_marca: str, autor: Annotated[Usuario, Depends(_exige_gerir)]
    ) -> Restaurado:
        achada = marca(id_da_marca)
        if achada.lixeira is None:
            raise HTTPException(409, "A marca não está na lixeira")
        impacto = impacto_da_marca(achada.id)
        marcas.definir_lixeira(achada.id, None)
        try:
            registrar(
                "marca",
                "item.restaurado",
                achada,
                achada.lixeira.motivo,
                impacto.model_dump(),
                autor,
            )
        except Exception:
            marcas.definir_lixeira(achada.id, achada.lixeira)
            raise
        return Restaurado(id=achada.id, nome=achada.nome)

    def purgar(
        tipo: Literal["pessoa", "marca"],
        achada: Any,
        pedido: PedidoDePurga,
        autor: Usuario,
    ) -> Restaurado:
        login_recente_ou_403(autor, relogio(), login_recente)
        if achada.lixeira is None:
            raise HTTPException(409, "Só se purga o que está na lixeira")
        if pedido.nome != achada.nome:
            raise HTTPException(422, "O nome digitado não é o do item")
        impacto = (
            impacto_da_pessoa(achada.id, 0)
            if tipo == "pessoa"
            else impacto_da_marca(achada.id)
        )
        # O registro vem antes: se falha, nada é apagado.
        registrar(
            tipo,
            "item.purgado",
            achada,
            achada.lixeira.motivo,
            impacto.model_dump(),
            autor,
        )
        try:
            (pessoas if tipo == "pessoa" else marcas).apagar(achada.id)
        except (PessoaInexistente, MarcaInexistente):
            raise HTTPException(409, "O item já saiu da lixeira") from None
        return Restaurado(id=achada.id, nome=achada.nome)

    @rotas.post("/pessoas/{id_da_pessoa}/purgar")
    def purgar_pessoa(
        id_da_pessoa: str,
        pedido: PedidoDePurga,
        autor: Annotated[Usuario, Depends(_exige_gerir)],
    ) -> Restaurado:
        return purgar("pessoa", pessoa(id_da_pessoa), pedido, autor)

    @rotas.post("/marcas/{id_da_marca}/purgar")
    def purgar_marca(
        id_da_marca: str,
        pedido: PedidoDePurga,
        autor: Annotated[Usuario, Depends(_exige_gerir)],
    ) -> Restaurado:
        return purgar("marca", marca(id_da_marca), pedido, autor)

    return rotas
