"""Adaptador do faster-whisper: o único lugar que importa a biblioteca.

O grupo de dependências `transcricao` não entra no `make verificar`; os testes
passam um modelo falso. Sem `initial_prompt` nem `hotwords`: o Whisper não pode
receber o perfil nem nomes de pessoas.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from api.dispositivo import Dispositivo, exigir_gpu, ler_dispositivo
from api.transcricao import Palavra, Transcricao

log = logging.getLogger(__name__)

NOME_DO_MODELO = "large-v3-turbo"
IDIOMA = "pt"

# O dispositivo do CTranslate2 e a precisão em cada um. Na L4, float16 usa os tensor
# cores sem perder precisão; int8 é o que roda bem na CPU.
DISPOSITIVOS = {"cpu": ("cpu", "int8"), "gpu": ("cuda", "float16")}

# Detecção de voz (Silero, a do faster-whisper): o Whisper pula o que não é fala, e os
# tempos das palavras continuam contados do início do arquivo. Limiar abaixo do padrão
# (0,5) para não cortar fala baixa sobre música; silêncio mínimo e margem são os padrões
# da biblioteca (2 s e 400 ms), que só tiram pausa longa.
VAD_PARAMETROS = {
    "threshold": 0.35,
    "min_silence_duration_ms": 2000,
    "speech_pad_ms": 400,
}


def _gpus() -> int:
    import ctranslate2

    return int(ctranslate2.get_cuda_device_count())


def _carregar(
    pasta_do_modelo: str,
    dispositivo: Dispositivo = "cpu",
    gpus: Callable[[], int] | None = None,
) -> Any:
    from faster_whisper import WhisperModel

    if dispositivo == "gpu":
        exigir_gpu((gpus or _gpus)(), "o CTranslate2")
    device, compute_type = DISPOSITIVOS[dispositivo]
    log.info("Transcrição em %s (%s, %s)", dispositivo, device, compute_type)
    # local_files_only: o Job roda sem internet, com o modelo da imagem.
    return WhisperModel(
        pasta_do_modelo,
        device=device,
        compute_type=compute_type,
        local_files_only=True,
    )


class TranscritorFasterWhisper:
    def __init__(self, modelo: Any) -> None:
        self._modelo = modelo

    @classmethod
    def da_pasta(
        cls,
        pasta_do_modelo: str,
        dispositivo: Dispositivo | None = None,
        carregar: Callable[..., Any] = _carregar,
    ) -> "TranscritorFasterWhisper":
        """`dispositivo` vem da variável `DISPOSITIVO` (cpu, por padrão) se não for dado."""
        return cls(carregar(pasta_do_modelo, dispositivo or ler_dispositivo()))

    def transcrever(self, audio: Path) -> Transcricao:
        segmentos, _ = self._modelo.transcribe(
            str(audio),
            language=IDIOMA,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=VAD_PARAMETROS,
        )
        palavras = [
            Palavra(texto=p.word.strip(), inicio_s=p.start, fim_s=p.end)
            for segmento in segmentos
            for p in (segmento.words or [])
            if p.word.strip()
        ]
        return Transcricao(modelo=NOME_DO_MODELO, idioma=IDIOMA, palavras=palavras)
