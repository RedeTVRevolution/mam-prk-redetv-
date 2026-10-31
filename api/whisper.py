"""Adaptador do faster-whisper: o único lugar que importa a biblioteca.

O grupo de dependências `transcricao` não entra no `make verificar`; os testes
passam um modelo falso. Sem `initial_prompt` nem `hotwords`: o Whisper não pode
receber o perfil nem nomes de pessoas.
"""

from pathlib import Path
from typing import Any

from api.transcricao import Palavra, Transcricao

NOME_DO_MODELO = "large-v3-turbo"
IDIOMA = "pt"


def _carregar(pasta_do_modelo: str) -> Any:
    from faster_whisper import WhisperModel

    # Em CPU; local_files_only: o Job roda sem internet, com o modelo da imagem.
    return WhisperModel(
        pasta_do_modelo, device="cpu", compute_type="int8", local_files_only=True
    )


class TranscritorFasterWhisper:
    def __init__(self, modelo: Any) -> None:
        self._modelo = modelo

    @classmethod
    def da_pasta(cls, pasta_do_modelo: str) -> "TranscritorFasterWhisper":
        return cls(_carregar(pasta_do_modelo))

    def transcrever(self, audio: Path) -> Transcricao:
        segmentos, _ = self._modelo.transcribe(
            str(audio), language=IDIOMA, word_timestamps=True
        )
        palavras = [
            Palavra(texto=p.word.strip(), inicio_s=p.start, fim_s=p.end)
            for segmento in segmentos
            for p in (segmento.words or [])
            if p.word.strip()
        ]
        return Transcricao(modelo=NOME_DO_MODELO, idioma=IDIOMA, palavras=palavras)
