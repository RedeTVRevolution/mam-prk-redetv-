"""O bucket das fotos de referência das pessoas, sem depender de relatório nem de rota."""

from typing import Protocol

from api.catalogo import Catalogo, PessoaDoCatalogo, prefixo_das_fotos


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


def apagar_fotos_da_pessoa(
    fotos: FotosDeReferencia, pessoas: Catalogo, pessoa: PessoaDoCatalogo
) -> None:
    """Rosto é dado sensível: as fotos da pessoa saem já (as da lista de rostos e, pela
    pasta, as da web trocadas antes) e a lista fica vazia."""
    for rosto in pessoa.rostos:
        fotos.apagar(rosto.referencia)
    fotos.apagar_prefixo(prefixo_das_fotos(pessoa.id))
    pessoas.definir_rostos(pessoa.id, [])
