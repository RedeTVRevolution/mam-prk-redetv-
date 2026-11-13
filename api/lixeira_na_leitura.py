"""A lixeira do catálogo vale na leitura (#583, #591): a regra de quem conta e a versão do
estado da lixeira.

Nada é gravado no BigQuery nem no índice: o que a leitura devolve é filtrado pelo estado
atual do catálogo. **Um id de pessoa conta** se existe no catálogo, está fora da lixeira e,
se foi fundido, o destino final da cadeia conta. A conferência é positiva, uma leitura em
lote do catálogo sobre os ids encontrados (a pessoa purgada não aparece em lista nenhuma).

A **versão** é um marcador durável no Firestore, lido por todas as instâncias e avançado a
cada envio, restauração, purga (manual e automática) e fusão. Só cresce, então enviar e
purgar a mesma pessoa não devolve um valor já visto, o que a impressão das pessoas na
lixeira não garantiria. A busca a usa para recusar o cursor velho.
"""

from collections.abc import Iterable
from typing import Any, Protocol

from google.cloud import firestore

from api.catalogo import Catalogo, PessoaDoCatalogo

# Uma cadeia de fusões (A→B→C) tem poucos elos; o teto só corta um ciclo gravado errado,
# e quem não chega a um destino que conta fica de fora.
SALTOS_MAXIMOS_DA_FUSAO = 10

COLECAO_DO_ESTADO_DA_LIXEIRA = "estado_da_lixeira"
DOCUMENTO_DA_VERSAO = "catalogo"


def pessoas_que_contam(catalogo: Catalogo, ids: Iterable[str]) -> set[str]:
    """Os `ids` que contam, em uma leitura em lote por elo da cadeia de fusões."""
    ponta = {i: i for i in ids}  # o id pedido -> onde a cadeia está agora
    lidas: dict[str, PessoaDoCatalogo | None] = {}
    contam: set[str] = set()
    for _ in range(SALTOS_MAXIMOS_DA_FUSAO + 1):
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
            else:
                ponta[pedido] = pessoa.fundida.destino_id
        if not ponta:
            break
    return contam


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
