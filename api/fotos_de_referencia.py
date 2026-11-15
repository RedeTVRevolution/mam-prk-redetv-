"""O bucket das fotos de referência das pessoas, sem depender de relatório nem de rota."""

from typing import Protocol


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
