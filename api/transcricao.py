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

    def recortar(self, inicio_ms: int, fim_ms: int) -> "Transcricao":
        """As palavras cujo meio cai em `[inicio_ms, fim_ms]`."""
        return self.model_copy(
            update={
                "palavras": [
                    p
                    for p in self.palavras
                    if inicio_ms <= (p.inicio_s + p.fim_s) * 500 <= fim_ms
                ]
            }
        )

    def em_linhas(self) -> str:
        """Uma linha por trecho, `[MM:SS] texto`, para a instrução do Gemini.

        O trecho muda quando há pausa de mais de 1 s ou passa de 15 palavras.
        """
        linhas: list[str] = []
        atual: list[Palavra] = []
        for p in self.palavras:
            if atual and (p.inicio_s - atual[-1].fim_s > 1 or len(atual) >= 15):
                linhas.append(_linha(atual))
                atual = []
            atual.append(p)
        if atual:
            linhas.append(_linha(atual))
        return "\n".join(linhas)


def _linha(palavras: list[Palavra]) -> str:
    segundos = int(palavras[0].inicio_s)
    texto = " ".join(p.texto for p in palavras)
    return f"[{segundos // 60:02d}:{segundos % 60:02d}] {texto}"


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
