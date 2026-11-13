"""Catálogo de marcas (#150), no molde do de pessoas: id estável, nome e apelidos.

Alimenta o autocompletar da marca do comercial. A carga inicial junta as marcas já
vistas nos comerciais das Decupagens; o nome novo digitado por quem corrige entra
como "a revisar".
"""

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from pydantic import BaseModel

from api.catalogo import EnvioParaLixeira, novo_id
from api.comparador import normalizar


class MarcaDoCatalogo(BaseModel):
    id: str
    nome: str
    apelidos: list[str] = []
    a_revisar: bool = False
    acrescentada_por: str | None = None
    # Na lixeira (#151): some do autocompletar; fica até a purga.
    lixeira: EnvioParaLixeira | None = None


class MarcaInexistente(Exception):
    """Nenhuma marca do catálogo tem o id pedido."""


def nomes_de_busca_da_marca(marca: MarcaDoCatalogo) -> list[str]:
    """Nome e apelidos normalizados: o que `achar` compara."""
    return sorted({normalizar(n) for n in [marca.nome, *marca.apelidos]})


class CatalogoDeMarcas(Protocol):
    """Porta para o Firestore; os testes usam uma versão em memória."""

    def obter(self, id: str) -> MarcaDoCatalogo | None: ...

    def obter_varios(self, ids: Iterable[str]) -> dict[str, MarcaDoCatalogo]:
        """As marcas que existem entre os `ids`, numa leitura em lote."""
        ...

    def achar(
        self, nome: str, *, com_lixeira: bool = False
    ) -> list[MarcaDoCatalogo]:
        """As marcas cujo nome ou apelido é `nome`, sem maiúsculas nem acentos; as da
        lixeira só com `com_lixeira` (a carga não pode recriá-las, #596)."""
        ...

    def todas(self) -> list[MarcaDoCatalogo]:
        """As marcas que não estão na lixeira."""
        ...

    def na_lixeira(self) -> list[MarcaDoCatalogo]: ...

    def definir_lixeira(
        self, id: str, envio: EnvioParaLixeira | None
    ) -> MarcaDoCatalogo:
        """Manda para a lixeira (ou, com `None`, tira); `MarcaInexistente` se o id não existe."""
        ...

    def apagar(self, id: str) -> None:
        """`MarcaInexistente` se o id não existe."""
        ...

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

    def obter_varios(self, ids: Iterable[str]) -> dict[str, MarcaDoCatalogo]:
        return {i: self._marcas[i] for i in dict.fromkeys(ids) if i in self._marcas}

    def achar(
        self, nome: str, *, com_lixeira: bool = False
    ) -> list[MarcaDoCatalogo]:
        chave = normalizar(nome)
        marcas = self._marcas.values() if com_lixeira else self.todas()
        return [m for m in marcas if chave in nomes_de_busca_da_marca(m)]

    def todas(self) -> list[MarcaDoCatalogo]:
        return [m for m in self._marcas.values() if m.lixeira is None]

    def na_lixeira(self) -> list[MarcaDoCatalogo]:
        return [m for m in self._marcas.values() if m.lixeira is not None]

    def definir_lixeira(
        self, id: str, envio: EnvioParaLixeira | None
    ) -> MarcaDoCatalogo:
        atual = self._marcas.get(id)
        if atual is None:
            raise MarcaInexistente(id)
        self._marcas[id] = atual.model_copy(update={"lixeira": envio})
        return self._marcas[id]

    def apagar(self, id: str) -> None:
        if self._marcas.pop(id, None) is None:
            raise MarcaInexistente(id)

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
    nome ou apelido, sem acento nem maiúscula), inclusive entre as da lixeira: marca
    na lixeira não é recriada, só depois da purga (#596). Idempotente; devolve quantas
    entraram."""
    entraram = 0
    for decupagem in decupagens:
        for marca in marcas_dos_comerciais(decupagem):
            if catalogo.achar(marca, com_lixeira=True):
                continue
            catalogo.acrescentar(marca, [])
            entraram += 1
    return entraram
