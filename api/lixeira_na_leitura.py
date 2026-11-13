"""A lixeira do catálogo vale na leitura (#583, #591): a regra de quem conta e a versão do
estado da lixeira.

Nada é gravado no BigQuery nem no índice: o que a leitura devolve é filtrado pelo estado
atual do catálogo. **Um id de pessoa conta** se existe no catálogo, está fora da lixeira e,
se foi fundido, o destino final da cadeia conta. A conferência é positiva, uma leitura em
lote do catálogo sobre os ids encontrados (a pessoa purgada não aparece em lista nenhuma).

A **marca** na lixeira (#593) é o contrário: conta tudo, menos o texto que bate com o nome
ou um apelido (`nomes_de_busca_da_marca`) de uma marca na lixeira; a marca purgada já não
está lá e volta a contar.

A **versão** é um marcador durável no Firestore, lido por todas as instâncias e avançado a
cada envio, restauração, purga (manual e automática) e fusão. Só cresce, então enviar e
purgar a mesma pessoa não devolve um valor já visto, o que a impressão das pessoas na
lixeira não garantiria. A busca a usa para recusar o cursor velho.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Protocol

from google.cloud import firestore
from pydantic import BaseModel

from api.catalogo import Catalogo, PessoaDoCatalogo
from api.marcas import CatalogoDeMarcas, MarcaDoCatalogo, nomes_de_busca_da_marca

COLECAO_DO_ESTADO_DA_LIXEIRA = "estado_da_lixeira"
COLECAO_DAS_PURGAS_DE_MARCA = "purgas_de_marca"
DOCUMENTO_DA_VERSAO = "catalogo"


def pessoas_que_contam(catalogo: Catalogo, ids: Iterable[str]) -> set[str]:
    """Os `ids` que contam, em uma leitura em lote por elo da cadeia de fusões.
    (`catalogo_apagado.destino_final` anda a mesma cadeia, mas lê uma pessoa por vez.)
    A cadeia vale de qualquer tamanho; só um id que se repete (ciclo gravado errado)
    a corta, e então o pedido não conta."""
    ponta = {i: i for i in ids}  # o id pedido -> onde a cadeia está agora
    vistos = {i: {i} for i in ponta}
    lidas: dict[str, PessoaDoCatalogo | None] = {}
    contam: set[str] = set()
    while ponta:
        novos = {p for p in ponta.values() if p not in lidas}
        if novos:
            lidas.update(dict.fromkeys(novos))
            lidas.update(catalogo.obter_varios(novos))
        for pedido, onde in list(ponta.items()):
            pessoa = lidas[onde]
            if pessoa is None or pessoa.lixeira is not None:
                del ponta[pedido]
            elif pessoa.fundida is None:
                contam.add(pedido)
                del ponta[pedido]
            elif pessoa.fundida.destino_id in vistos[pedido]:
                del ponta[pedido]
            else:
                vistos[pedido].add(pessoa.fundida.destino_id)
                ponta[pedido] = pessoa.fundida.destino_id
    return contam


def nomes_de_marca_na_lixeira(marcas: CatalogoDeMarcas) -> set[str]:
    """Nome e apelidos, normalizados, das marcas na lixeira: o texto que não conta."""
    return {n for m in marcas.na_lixeira() for n in nomes_de_busca_da_marca(m)}


class VersaoDaLixeira(Protocol):
    def atual(self) -> int:
        """A versão de agora (0 enquanto nada mudou)."""
        ...

    def avancar(self) -> None:
        """Marca que o estado da lixeira do catálogo mudou."""
        ...


class VersaoDaLixeiraEmMemoria:
    def __init__(self) -> None:
        self._valor = 0

    def atual(self) -> int:
        return self._valor

    def avancar(self) -> None:
        self._valor += 1


class VersaoDaLixeiraFirestore:
    """Um documento com um contador; `Increment` é atômico entre as instâncias."""

    def __init__(
        self, cliente: Any, colecao: str = COLECAO_DO_ESTADO_DA_LIXEIRA
    ) -> None:
        self._documento = cliente.collection(colecao).document(DOCUMENTO_DA_VERSAO)

    def atual(self) -> int:
        return int((self._documento.get().to_dict() or {}).get("versao", 0))

    def avancar(self) -> None:
        self._documento.set({"versao": firestore.Increment(1)}, merge=True)


class PurgaDeMarca(BaseModel):
    """O que a purga de uma marca deixa (#595): o relatório de marcas corta por `em` as
    ocorrências de `nomes` (nome e apelidos normalizados) em vídeos de Jobs criados antes."""

    nome: str
    apelidos: list[str]
    nomes: list[str]
    em: datetime


class PurgasDeMarca(Protocol):
    def gravar(self, marca: MarcaDoCatalogo, em: datetime) -> None:
        """Grava o registro; a purga chama antes de apagar a marca."""
        ...

    def todas(self) -> list[PurgaDeMarca]: ...


def _registro_da_purga(marca: MarcaDoCatalogo, em: datetime) -> PurgaDeMarca:
    return PurgaDeMarca(
        nome=marca.nome,
        apelidos=marca.apelidos,
        nomes=nomes_de_busca_da_marca(marca),
        em=em,
    )


class PurgasDeMarcaEmMemoria:
    def __init__(self) -> None:
        self._purgas: list[PurgaDeMarca] = []

    def gravar(self, marca: MarcaDoCatalogo, em: datetime) -> None:
        self._purgas.append(_registro_da_purga(marca, em))

    def todas(self) -> list[PurgaDeMarca]:
        return list(self._purgas)


class PurgasDeMarcaFirestore:
    """Um documento por purga; as instâncias leem a coleção inteira (poucos registros)."""

    def __init__(
        self, cliente: Any, colecao: str = COLECAO_DAS_PURGAS_DE_MARCA
    ) -> None:
        self._colecao = cliente.collection(colecao)

    def gravar(self, marca: MarcaDoCatalogo, em: datetime) -> None:
        self._colecao.document(uuid.uuid4().hex).set(
            _registro_da_purga(marca, em).model_dump()
        )

    def todas(self) -> list[PurgaDeMarca]:
        return [PurgaDeMarca(**(d.to_dict() or {})) for d in self._colecao.stream()]


def cortes_das_purgas(purgas: PurgasDeMarca) -> dict[str, datetime]:
    """Por nome normalizado, a purga mais recente: só vale a de cima, porque ela cobre
    tudo o que as anteriores já cortavam."""
    cortes: dict[str, datetime] = {}
    for p in purgas.todas():
        for n in p.nomes:
            cortes[n] = max(p.em, cortes.get(n, p.em))
    return cortes
