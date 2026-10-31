"""A transcrição do Whisper: formato guardado, portas e dublê em memória.

O Whisper não recebe perfil nem nomes de pessoas: a transcrição dele é a fonte
independente que a conferência de nomes usa. Cada palavra guarda o tempo em segundos.
"""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

VERSAO_DO_FORMATO = 1


class Palavra(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texto: str
    inicio_s: float
    fim_s: float


class Transcricao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versao: int = VERSAO_DO_FORMATO
    modelo: str
    idioma: str
    palavras: list[Palavra]

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palavras)


class Transcritor(Protocol):
    """Porta do motor de transcrição; a importação do faster-whisper fica só no adaptador."""

    def transcrever(self, audio: Path) -> Transcricao: ...


class TranscricoesDoJob(Protocol):
    """Porta do Cloud Storage: o áudio da validação e a transcrição guardada."""

    def baixar_audio(self, job_id: str, destino: Path) -> bool:
        """Grava o áudio em `destino`; `False` se o vídeo não tem faixa de áudio."""
        ...

    def gravar_transcricao(self, job_id: str, transcricao: Transcricao) -> None: ...

    def ler_transcricao(self, job_id: str) -> Transcricao | None: ...


class TranscricoesEmMemoria:
    def __init__(self, audios: dict[str, bytes] | None = None) -> None:
        self.audios = audios or {}
        self._guardadas: dict[str, str] = {}

    def baixar_audio(self, job_id: str, destino: Path) -> bool:
        if job_id not in self.audios:
            return False
        destino.write_bytes(self.audios[job_id])
        return True

    def gravar_transcricao(self, job_id: str, transcricao: Transcricao) -> None:
        self._guardadas[job_id] = transcricao.model_dump_json()

    def ler_transcricao(self, job_id: str) -> Transcricao | None:
        conteudo = self._guardadas.get(job_id)
        return None if conteudo is None else Transcricao.model_validate_json(conteudo)
