"""O que a lixeira do catálogo grava para a leitura (#583, #591): a versão do estado da
lixeira e o registro da purga de marca. Quem decide o que conta na leitura é o Quem conta
(`api.quem_conta`, #610).

Nada é gravado no BigQuery nem no índice: o que a leitura devolve é filtrado pelo estado
atual do catálogo.

A **versão** é um marcador durável no Firestore, lido por todas as instâncias e avançado a
cada envio, restauração, purga (manual e automática) e fusão. Só cresce, então enviar e
purgar a mesma pessoa não devolve um valor já visto, o que a impressão das pessoas na
lixeira não garantiria. A busca a usa para recusar o cursor velho.
"""

import uuid
from datetime import datetime
from typing import Any, Protocol

from google.cloud import firestore
from pydantic import BaseModel

from api.marcas import MarcaDoCatalogo, nomes_de_busca_da_marca

COLECAO_DO_ESTADO_DA_LIXEIRA = "estado_da_lixeira"
COLECAO_DAS_PURGAS_DE_MARCA = "purgas_de_marca"
DOCUMENTO_DA_VERSAO = "catalogo"


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
    # A marca que foi purgada. Se a marca ainda existe no catálogo, a purga não aconteceu
    # (gravou o registro e o apagar falhou): o registro não vale. Sem id (gravado antes
    # deste campo), vale.
    marca_id: str | None = None


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
        marca_id=marca.id,
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
