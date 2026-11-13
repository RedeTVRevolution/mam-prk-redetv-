"""Lixeira das pessoas e marcas do catálogo (E8, #151), em `/v1/admin/lixeira`.

Mandar para a lixeira é do Curador e do Administrador (`catalogo.apagar`); restaurar e
purgar, só do Administrador (`lixeira.gerir`). A pessoa perde já as fotos de rosto (LGPD) e,
na leitura das Decupagens, o nome que só o rosto sustentava; a marca perde o vínculo com o
catálogo e mantém o texto. A saída do modelo não é tocada (ADR 0010).
"""

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
from api.correcoes import RepositorioDeCorrecoes
from api.jobs import FiltroDeJobs, RepositorioDeJobs, _confere_permissao
from api.leitura_da_decupagem import decupagens_corrigidas
from api.lixeira import (
    PRAZO_DA_PURGA,
    Envio,
    ItemDaLixeira,
    _exige_gerir,
    item_da_lixeira,
    login_recente_ou_403,
)
from api.lixeira_na_leitura import PurgasDeMarca
from api.marcas import (
    CatalogoDeMarcas,
    MarcaDoCatalogo,
    MarcaInexistente,
    nomes_de_busca_da_marca,
)
from api.relatorio_de_marcas import ConsultaDeInsercoes, SoMarcasQueContam
from api.relatorios import ou_503
from api.texto_como_dado import Linha

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
    # O que o relatório de marcas deixa de contar, pelo nome e pelos apelidos (#597); sem
    # relatório configurado, 0. A busca entra só no texto da tela, sem número.
    insercoes_que_saem_do_relatorio: int = 0


def _exige_apagar(request: Request, chamador: ChamadorAutenticado) -> Usuario:
    """Dependência: só pessoa com `catalogo.apagar`; chave de sistema não mexe no catálogo."""
    if not isinstance(chamador, Usuario):
        raise HTTPException(403, "Chave de sistema não mexe no catálogo")
    _confere_permissao(request, chamador, "catalogo.apagar")
    return chamador


class PedidoDePurga(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # O nome, digitado: a prova de que a pessoa sabe o que está apagando.
    nome: Annotated[str, Linha(255)]


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
    purgas_de_marca: PurgasDeMarca,
    ao_mudar: Callable[[], None] = lambda: None,
) -> int:
    """Purga as pessoas e marcas na lixeira há `PRAZO_DA_PURGA` ou mais; devolve quantas.
    Cada uma grava o registro antes de sair (e a marca, o da purga, #595); a que falha fica
    e a próxima execução tenta.
    `ao_mudar` avança a versão da lixeira (#591) antes e depois de cada purga: se o avanço
    falha, o item continua na lixeira e a próxima varredura tenta de novo."""
    purgadas = 0
    itens: list[tuple[Literal["pessoa", "marca"], Any, EnvioParaLixeira]] = [
        ("pessoa", p, p.lixeira) for p in pessoas.na_lixeira() if p.lixeira
    ] + [("marca", m, m.lixeira) for m in marcas.na_lixeira() if m.lixeira]
    for tipo, item, envio in itens:
        if agora - envio.em < PRAZO_DA_PURGA:
            continue
        try:
            ao_mudar()  # antes: se falha, nada muda
            auditoria.acrescentar(
                _registro(
                    tipo,
                    "item.purgado",
                    item.id,
                    item.nome,
                    envio.motivo,
                    {},
                    agora,
                    None,
                )
            )
            if tipo == "marca":
                purgas_de_marca.gravar(item, agora)
            (pessoas if tipo == "pessoa" else marcas).apagar(item.id)
            ao_mudar()  # depois: fecha a janela de uma 1ª página entre o avanço e a mudança
        except Exception:
            log.exception("a purga de %s %s falhou", tipo, item.id)
            continue
        purgadas += 1
    return purgadas


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
    purgas_de_marca: PurgasDeMarca,
    relatorio_de_marcas: ConsultaDeInsercoes | None,
    descartar_pessoas: Callable[[], None] = lambda: None,
    ao_mudar: Callable[[], None] = lambda: None,
) -> APIRouter:
    """`descartar_pessoas` descarta a cópia curta das pessoas (#364): quem entra na
    lixeira ou sai dela muda o autocompletar e a grafia aproximada da busca na hora.
    `ao_mudar` avança a versão da lixeira (#591) antes e depois de cada envio, restauração
    e purga: antes, para que uma falha dele deixe o catálogo como estava; depois, para
    fechar a janela de uma 1ª página lida entre o avanço e a mudança."""
    rotas = APIRouter(prefix="/admin/lixeira")

    def lixeira_da_pessoa(id: str, envio: EnvioParaLixeira | None) -> None:
        ao_mudar()
        pessoas.definir_lixeira(id, envio)
        descartar_pessoas()
        ao_mudar()

    def lixeira_da_marca(id: str, envio: EnvioParaLixeira | None) -> None:
        ao_mudar()
        marcas.definir_lixeira(id, envio)
        ao_mudar()

    def entregues(filtro: FiltroDeJobs) -> Iterator[dict[str, Any]]:
        return decupagens_corrigidas(
            repositorio, correcoes, decupagens, pessoas, filtro
        )

    def insercoes_do_relatorio(achada: MarcaDoCatalogo) -> int:
        if relatorio_de_marcas is None:
            return 0
        so = SoMarcasQueContam(
            relatorio_de_marcas, marcas, purgas_de_marca, repositorio
        )
        nomes = set(nomes_de_busca_da_marca(achada))
        return ou_503(lambda: so.insercoes_dos_nomes(nomes))

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

    def impacto_da_marca(achada: MarcaDoCatalogo) -> ImpactoDaMarca:
        return ImpactoDaMarca(
            ocorrencias_que_perdem_o_vinculo=sum(
                1
                for d in entregues(FiltroDeJobs(marca_do_catalogo=achada.id))
                for c in d.get("comerciais") or []
                if c.get("catalogo_id") == achada.id
            ),
            insercoes_que_saem_do_relatorio=insercoes_do_relatorio(achada),
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
        return impacto_da_marca(marca(id_da_marca))

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
        ao_mudar()  # antes das fotos: apagá-las não se desfaz
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
        impacto = impacto_da_marca(achada)
        envio = envio_de(autor, pedido.motivo)
        lixeira_da_marca(achada.id, envio)
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
            lixeira_da_marca(achada.id, None)
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
        impacto = impacto_da_marca(achada)
        lixeira_da_marca(achada.id, None)
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
            lixeira_da_marca(achada.id, achada.lixeira)
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
            else impacto_da_marca(achada)
        )
        ao_mudar()  # antes do registro e da purga: se falha, nada muda
        # O registro vem antes: se falha, nada é apagado.
        registrar(
            tipo,
            "item.purgado",
            achada,
            achada.lixeira.motivo,
            impacto.model_dump(),
            autor,
        )
        if tipo == "marca":
            purgas_de_marca.gravar(achada, relogio())  # antes de apagar: se falha, fica
        try:
            (pessoas if tipo == "pessoa" else marcas).apagar(achada.id)
        except (PessoaInexistente, MarcaInexistente):
            raise HTTPException(409, "O item já saiu da lixeira") from None
        ao_mudar()
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
