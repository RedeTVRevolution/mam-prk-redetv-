"""Cadastro de marcas do Curador (`/v1/catalogo/marcas/cadastro`, `.../{id}/apelidos` e
`.../{id}/juntar`): quem tem `catalogo.fundir` (Curador e Administrador) cadastra a marca com
apelidos, troca os apelidos e junta duas marcas numa.

O apelido é como a leitura errada do modelo ("UniAefel" para "UNIFAEL") passa a contar como
a marca do catálogo em todo o relatório e na busca, inclusive nos vídeos antigos, sem
reprocessar (`api.marcas.MarcasCanonicas`). A chave de uma grafia (`chave_da_marca`) ignora
maiúscula, acento, pontuação e espaço, e é única no catálogo, a lixeira incluída: nome ou
apelido que já é de outra marca dá 409 e manda juntar. Apelido que repete outro, ou o próprio
nome, é descartado em silêncio.

Toda mudança vai para a auditoria; sem o registro, a mudança é desfeita. Depois de cada
escrita, `descartar` joga fora a cópia do autocompletar e invalida os cursores da busca (o
grupo da marca mudou).
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from api.auditoria import Acao, RepositorioDeAuditoria, registro_de_auditoria
from api.auth import Usuario
from api.correcoes import sem_controle
from api.decupagem import LIMITE_DO_NOME
from api.erros import lido
from api.marcas import CatalogoDeMarcas, MarcaDoCatalogo
from api.permissoes import exige
from api.rotas_dos_programas import LIMITE_DE_APELIDOS, Apelido, apelidos_validos
from api.texto import chave_da_marca, normalizar
from api.texto_como_dado import ID_SEGURO, Linha

Nome = Annotated[str, Linha(LIMITE_DO_NOME, min_length=1, strip=True)]


class MarcaDoCadastro(BaseModel):
    id: str
    nome: str
    apelidos: list[str]


class NovaMarca(BaseModel):
    nome: Nome
    apelidos: list[Apelido] = []

    _sem_controle_no_nome = field_validator("nome")(sem_controle)
    _apelidos_validos = field_validator("apelidos")(apelidos_validos)


class NovosApelidos(BaseModel):
    apelidos: list[Apelido]

    _apelidos_validos = field_validator("apelidos")(apelidos_validos)


class PedidoDeJuntar(BaseModel):
    outra_id: Annotated[str, Linha(64, min_length=1), ID_SEGURO]


def _sem_repeticao(nome: str, apelidos: list[str]) -> list[str]:
    """Os apelidos sem o que repete outro (mesma chave) ou o próprio nome."""
    vistas = {chave_da_marca(nome)}
    limpos: list[str] = []
    for apelido in apelidos:
        if (chave := chave_da_marca(apelido)) not in vistas:
            vistas.add(chave)
            limpos.append(apelido)
    return limpos


def _publica(marca: MarcaDoCatalogo) -> MarcaDoCadastro:
    return MarcaDoCadastro(id=marca.id, nome=marca.nome, apelidos=list(marca.apelidos))


def criar_rotas_do_cadastro_de_marcas(
    marcas: CatalogoDeMarcas,
    auditoria: RepositorioDeAuditoria,
    relogio: Callable[[], datetime],
    descartar: Callable[[], None],
) -> APIRouter:
    rotas = APIRouter()
    permissao = Depends(
        exige("catalogo.fundir", "Chave de sistema não mexe no catálogo")
    )
    Autor = Annotated[Usuario, permissao]

    def viva(id: str) -> MarcaDoCatalogo:
        achada = lido(lambda: marcas.obter(id))
        if achada is None or achada.lixeira is not None:
            raise HTTPException(404, "Marca não encontrada")
        return achada

    def sem_conflito(id: str | None, nome: str, apelidos: list[str]) -> None:
        """409 se a chave do nome ou de um apelido já é de OUTRA marca (a lixeira conta)."""
        donos: dict[str, tuple[MarcaDoCatalogo, bool]] = {}
        for na_lixeira, lista in (
            (False, lido(marcas.todas)),
            (True, lido(marcas.na_lixeira)),
        ):
            for m in lista:
                if m.id != id:
                    for texto in (m.nome, *m.apelidos):
                        donos.setdefault(chave_da_marca(texto), (m, na_lixeira))
        for texto in (nome, *apelidos):
            if (dono := donos.get(chave_da_marca(texto))) is None:
                continue
            marca, na_lixeira = dono
            if na_lixeira:
                raise HTTPException(
                    409,
                    f"{texto} já é a marca {marca.nome}, que está na lixeira: "
                    "restaure ou apague essa marca antes",
                )
            raise HTTPException(409, f"{texto} já é a marca {marca.nome}: use Juntar")

    def registrar(
        autor: Usuario,
        acao: Acao,
        marca: MarcaDoCatalogo,
        detalhes: dict[str, object],
        desfazer: Callable[[], object],
    ) -> None:
        """Grava na auditoria; sem o registro, a mudança é desfeita (e a cópia, descartada)."""
        descartar()
        try:
            auditoria.acrescentar(
                registro_de_auditoria(
                    quando=relogio(),
                    quem=autor,
                    acao=acao,
                    alvo_tipo="marca",
                    alvo_id=marca.id,
                    alvo_nome=marca.nome,
                    detalhes=detalhes,
                )
            )
        except Exception:
            desfazer()
            descartar()
            raise

    @rotas.get("/marcas/cadastro")
    def listar(_autor: Autor) -> list[MarcaDoCadastro]:
        todas = lido(marcas.todas)
        todas.sort(key=lambda m: (normalizar(m.nome), m.nome, m.id))
        return [_publica(m) for m in todas]

    @rotas.post("/marcas/cadastro", status_code=201)
    def criar(nova: NovaMarca, autor: Autor) -> MarcaDoCadastro:
        apelidos = _sem_repeticao(nova.nome, nova.apelidos)
        # ponytail: conferir e criar não é atômico; dois POSTs simultâneos com a mesma
        # chave criam duas marcas (o rótulo fica com a de menor id; Juntar resolve). Se o
        # cadastro deixar de ser de um Curador só, reservar a chave numa transação.
        sem_conflito(None, nova.nome, apelidos)
        criada = marcas.acrescentar(nova.nome, apelidos, autor=autor.email or autor.uid)
        registrar(
            autor,
            "marca.criada",
            criada,
            {"apelidos": apelidos},
            lambda: marcas.apagar(criada.id),
        )
        return _publica(criada)

    @rotas.put("/marcas/{id_da_marca}/apelidos")
    def trocar_apelidos(
        id_da_marca: str, pedido: NovosApelidos, autor: Autor
    ) -> MarcaDoCadastro:
        antes = viva(id_da_marca)
        apelidos = _sem_repeticao(antes.nome, pedido.apelidos)
        sem_conflito(antes.id, antes.nome, apelidos)
        nova = marcas.definir_apelidos(antes.id, apelidos)
        registrar(
            autor,
            "marca.alterada",
            nova,
            {"apelidos_antes": antes.apelidos, "apelidos_depois": apelidos},
            lambda: marcas.definir_apelidos(antes.id, antes.apelidos),
        )
        return _publica(nova)

    @rotas.post("/marcas/{id_da_marca}/juntar")
    def juntar(
        id_da_marca: str, pedido: PedidoDeJuntar, autor: Autor
    ) -> MarcaDoCadastro:
        destino = viva(id_da_marca)
        if pedido.outra_id == destino.id:
            raise HTTPException(409, "Não dá para juntar uma marca nela mesma")
        outra = lido(lambda: marcas.obter(pedido.outra_id))
        if outra is None:
            raise HTTPException(404, "Marca não encontrada")
        if outra.lixeira is not None:
            raise HTTPException(
                409, "A outra marca está na lixeira: restaure ou apague antes"
            )
        apelidos = _sem_repeticao(
            destino.nome, [*destino.apelidos, outra.nome, *outra.apelidos]
        )
        if len(apelidos) > LIMITE_DE_APELIDOS:
            raise HTTPException(
                422, f"A marca ficaria com mais de {LIMITE_DE_APELIDOS} apelidos"
            )
        nova = marcas.definir_apelidos(destino.id, apelidos)
        # Sem registro a junção não vale: a outra marca ainda não foi apagada.
        registrar(
            autor,
            "marca.juntada",
            nova,
            {
                "outra_id": outra.id,
                "outra_nome": outra.nome,
                "apelidos_antes": destino.apelidos,
                "apelidos_depois": apelidos,
            },
            lambda: marcas.definir_apelidos(destino.id, destino.apelidos),
        )
        try:
            marcas.apagar(outra.id)  # sem purga: o nome dela passa a ser apelido desta
        except Exception:
            # A outra ficou: sem desfazer, o relatório seguiria com as duas marcas.
            marcas.definir_apelidos(destino.id, destino.apelidos)
            raise
        finally:
            descartar()
        return _publica(nova)

    return rotas
