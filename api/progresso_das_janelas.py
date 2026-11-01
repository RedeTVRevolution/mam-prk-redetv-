"""O que a análise por janelas guarda para retomar: o estado de cada janela e o
resultado das concluídas.

Uma nova execução do mesmo Job lê isto e não chama o Gemini de novo para a janela que
já tem Decupagem. O estado é o de `api/janelas.py`, da passada em curso; o resultado é a
Decupagem da janela, já medida pelo OCR. Durante o escalonamento, o estado é o dele e a
Decupagem continua a da primeira passada; `refeita` marca a janela que o escalonamento
já decupou de novo.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from api.decupagem import Decupagem
from api.janelas import EstadoJanela, Situacao


class JanelaGravada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indice: int
    situacao: Situacao
    tentativas: int
    erro: str | None = None
    decupagem: Decupagem | None = None
    refeita: bool = False

    @property
    def estado(self) -> EstadoJanela:
        return EstadoJanela(self.indice, self.situacao, self.tentativas, self.erro)

    @classmethod
    def de(
        cls,
        estado: EstadoJanela,
        decupagem: Decupagem | None = None,
        refeita: bool = False,
    ) -> "JanelaGravada":
        return cls(
            indice=estado.indice,
            situacao=estado.situacao,
            tentativas=estado.tentativas,
            erro=estado.erro,
            decupagem=decupagem,
            refeita=refeita,
        )


class JanelasDoJob(Protocol):
    """Porta do progresso das janelas. Cada janela tem o seu registro: gravar janelas
    diferentes ao mesmo tempo é seguro."""

    def ler(self, job_id: str) -> dict[int, JanelaGravada]: ...

    def gravar(self, job_id: str, janela: JanelaGravada) -> None: ...

    def apagar(self, job_id: str) -> None:
        """Descarta o progresso do Job, para a análise recomeçar do zero."""
        ...


class JanelasEmMemoria:
    def __init__(self) -> None:
        self._guardadas: dict[str, dict[int, str]] = {}

    def ler(self, job_id: str) -> dict[int, JanelaGravada]:
        return {
            indice: JanelaGravada.model_validate_json(conteudo)
            for indice, conteudo in self._guardadas.get(job_id, {}).items()
        }

    def gravar(self, job_id: str, janela: JanelaGravada) -> None:
        self._guardadas.setdefault(job_id, {})[janela.indice] = janela.model_dump_json()

    def apagar(self, job_id: str) -> None:
        self._guardadas.pop(job_id, None)
