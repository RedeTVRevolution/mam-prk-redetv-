"""O texto lido na tela, um quadro por segundo: formato guardado, portas e dublê em memória.

O OCR (PaddleOCR, local e sem internet) lê cada quadro do proxy. O resultado guarda, por
segundo, as linhas lidas com a posição de cada uma (caixa normalizada de 0 a 1, para não
depender da resolução do quadro). O tipo do texto continua sendo do Gemini.
"""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

VERSAO_DO_FORMATO = 1


class Caixa(BaseModel):
    """Retângulo do texto no quadro, em fração da largura e da altura."""

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    largura: float
    altura: float


class LinhaLida(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texto: str
    confianca: float
    caixa: Caixa


class QuadroLido(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segundo: int
    linhas: list[LinhaLida]


class LeituraDaTela(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versao: int = VERSAO_DO_FORMATO
    modelo: str
    quadros: list[QuadroLido]


class LeitorDeQuadro(Protocol):
    """Porta do OCR; a importação do PaddleOCR fica só no adaptador."""

    def ler(self, quadro: Path) -> list[LinhaLida]: ...


class LeiturasDoJob(Protocol):
    """Porta do Cloud Storage: o proxy do Job e a leitura da tela guardada."""

    def baixar_proxy(self, job_id: str, destino: Path) -> None: ...

    def gravar_leitura(self, job_id: str, leitura: LeituraDaTela) -> None: ...

    def ler_leitura(self, job_id: str) -> LeituraDaTela | None: ...


class LeiturasEmMemoria:
    def __init__(self, proxies: dict[str, bytes] | None = None) -> None:
        self.proxies = proxies or {}
        self._guardadas: dict[str, str] = {}

    def baixar_proxy(self, job_id: str, destino: Path) -> None:
        destino.write_bytes(self.proxies[job_id])

    def gravar_leitura(self, job_id: str, leitura: LeituraDaTela) -> None:
        self._guardadas[job_id] = leitura.model_dump_json()

    def ler_leitura(self, job_id: str) -> LeituraDaTela | None:
        conteudo = self._guardadas.get(job_id)
        return None if conteudo is None else LeituraDaTela.model_validate_json(conteudo)
