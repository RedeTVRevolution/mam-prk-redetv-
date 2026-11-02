"""Catálogo de marcas (#150), no molde do de pessoas: id estável, nome e apelidos.

Alimenta o autocompletar da marca do comercial. A carga inicial junta as marcas já
vistas nos comerciais das Decupagens; o nome novo digitado por quem corrige entra
como "a revisar".
"""

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from pydantic import BaseModel

from api.catalogo import novo_id
from api.comparador import normalizar


class MarcaDoCatalogo(BaseModel):
    id: str
    nome: str
    apelidos: list[str] = []
    a_revisar: bool = False
    acrescentada_por: str | None = None


def nomes_de_busca_da_marca(marca: MarcaDoCatalogo) -> list[str]:
    """Nome e apelidos normalizados: o que `achar` compara."""
    return sorted({normalizar(n) for n in [marca.nome, *marca.apelidos]})


class CatalogoDeMarcas(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def obter(self, id: str) -> MarcaDoCatalogo | None: ...

    def achar(self, nome: str) -> list[MarcaDoCatalogo]:
        """As marcas cujo nome ou apelido é `nome`, sem maiúsculas nem acentos."""
        ...

    def todas(self) -> list[MarcaDoCatalogo]: ...

    def acrescentar(
        self,
        nome: str,
        apelidos: list[str],
        *,
        a_revisar: bool = False,
        autor: str | None = None,
    ) -> MarcaDoCatalogo: ...


class CatalogoDeMarcasEmMemoria:
    def __init__(self) -> None:
        self._marcas: dict[str, MarcaDoCatalogo] = {}

    def obter(self, id: str) -> MarcaDoCatalogo | None:
        return self._marcas.get(id)

    def achar(self, nome: str) -> list[MarcaDoCatalogo]:
        chave = normalizar(nome)
        return [m for m in self._marcas.values() if chave in nomes_de_busca_da_marca(m)]

    def todas(self) -> list[MarcaDoCatalogo]:
        return list(self._marcas.values())

    def acrescentar(
        self,
        nome: str,
        apelidos: list[str],
        *,
        a_revisar: bool = False,
        autor: str | None = None,
    ) -> MarcaDoCatalogo:
        marca = MarcaDoCatalogo(
            id=novo_id(),
            nome=nome,
            apelidos=list(apelidos),
            a_revisar=a_revisar,
            acrescentada_por=autor,
        )
        self._marcas[marca.id] = marca
        return marca


def marcas_dos_comerciais(decupagem: Mapping[str, Any]) -> Iterable[str]:
    """As marcas escritas nos comerciais de uma Decupagem."""
    for comercial in decupagem.get("comerciais") or []:
        marca = str(comercial.get("marca", "")).strip()
        if marca:
            yield marca


def carregar_marcas(
    catalogo: CatalogoDeMarcas, decupagens: Iterable[Mapping[str, Any]]
) -> int:
    """Acrescenta ao catálogo as marcas dos comerciais que ainda não estão nele (pelo
    nome ou apelido, sem acento nem maiúscula). Idempotente; devolve quantas entraram."""
    entraram = 0
    for decupagem in decupagens:
        for marca in marcas_dos_comerciais(decupagem):
            if catalogo.achar(marca):
                continue
            catalogo.acrescentar(marca, [])
            entraram += 1
    return entraram
