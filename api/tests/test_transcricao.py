"""Job de transcrição, adaptador do faster-whisper e a porta da transcrição, sem modelo real."""

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from api.jobs import Estado, Job, RepositorioEmMemoria
from api.transcricao import Palavra, Transcricao, TranscricoesEmMemoria
from api.transcricao_job import executar
from api.whisper import TranscritorFasterWhisper

BASE = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def _palavra(texto: str, inicio: float, fim: float) -> Any:
    return SimpleNamespace(word=texto, start=inicio, end=fim)


class ModeloFalso:
    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []

    def transcribe(self, audio: str, **opcoes: Any) -> tuple[Any, Any]:
        self.chamadas.append({"audio": audio, **opcoes})
        segmentos = [
            SimpleNamespace(
                words=[_palavra(" Olá", 0.0, 0.4), _palavra(" mundo", 0.5, 0.9)]
            ),
            SimpleNamespace(
                words=[_palavra("  ", 1.0, 1.1), _palavra(" Andréa", 1.2, 1.7)]
            ),
            SimpleNamespace(words=None),
        ]
        return iter(segmentos), SimpleNamespace(language="pt")


class TranscritorFalso:
    def __init__(self, erro: Exception | None = None) -> None:
        self.erro = erro
        self.audios: list[Path] = []

    def transcrever(self, audio: Path) -> Transcricao:
        self.audios.append(audio)
        if self.erro:
            raise self.erro
        return Transcricao(
            modelo="falso",
            idioma="pt",
            palavras=[Palavra(texto="oi", inicio_s=0, fim_s=1)],
        )


def _repositorio(estado: Estado = "analisando") -> RepositorioEmMemoria:
    repositorio = RepositorioEmMemoria()
    repositorio.salvar(
        Job(
            id="j1",
            nome="j1.mp4",
            tamanho_bytes=1,
            estado=estado,
            criado_por="uid-1",
            criado_em=BASE,
            atualizado_em=BASE,
        )
    )
    return repositorio


def test_adaptador_nao_passa_prompt_nem_hotwords_e_guarda_o_tempo_de_cada_palavra(
    tmp_path: Path,
) -> None:
    modelo = ModeloFalso()

    transcricao = TranscritorFasterWhisper(modelo).transcrever(tmp_path / "a.wav")

    (chamada,) = modelo.chamadas
    assert "initial_prompt" not in chamada
    assert "hotwords" not in chamada
    assert chamada["language"] == "pt"
    assert chamada["word_timestamps"] is True
    assert transcricao.idioma == "pt"
    assert transcricao.modelo == "large-v3-turbo"
    assert [(p.texto, p.inicio_s, p.fim_s) for p in transcricao.palavras] == [
        ("Olá", 0.0, 0.4),
        ("mundo", 0.5, 0.9),
        ("Andréa", 1.2, 1.7),
    ]
    assert transcricao.texto == "Olá mundo Andréa"


def test_transcricao_com_tempos_e_gravada_e_lida_pela_porta() -> None:
    porta = TranscricoesEmMemoria()
    transcricao = Transcricao(
        modelo="large-v3-turbo",
        idioma="pt",
        palavras=[Palavra(texto="Olá", inicio_s=0.12, fim_s=0.48)],
    )

    assert porta.ler_transcricao("j1") is None
    porta.gravar_transcricao("j1", transcricao)

    assert porta.ler_transcricao("j1") == transcricao


def test_job_transcreve_o_audio_e_grava_sem_mudar_o_estado(tmp_path: Path) -> None:
    repositorio = _repositorio()
    porta = TranscricoesEmMemoria({"j1": b"RIFF"})
    transcritor = TranscritorFalso()

    executar("j1", repositorio, porta, transcritor, tmp_path)

    assert transcritor.audios == [tmp_path / "j1.wav"]
    gravada = porta.ler_transcricao("j1")
    assert gravada is not None and gravada.texto == "oi"
    assert repositorio.obter("j1").estado == "analisando"  # type: ignore[union-attr]


def test_video_sem_audio_grava_transcricao_vazia(tmp_path: Path) -> None:
    porta = TranscricoesEmMemoria()
    transcritor = TranscritorFalso()

    executar("j1", _repositorio(), porta, transcritor, tmp_path)

    assert transcritor.audios == []
    gravada = porta.ler_transcricao("j1")
    assert gravada is not None and gravada.palavras == []


def test_falha_da_transcricao_derruba_o_job_com_codigo_proprio(tmp_path: Path) -> None:
    repositorio = _repositorio()
    porta = TranscricoesEmMemoria({"j1": b"RIFF"})

    with pytest.raises(RuntimeError):
        executar(
            "j1", repositorio, porta, TranscritorFalso(RuntimeError("x")), tmp_path
        )

    job = repositorio.obter("j1")
    assert job is not None
    assert (job.estado, job.codigo_falha) == ("falhou", "transcricao_falhou")
    assert porta.ler_transcricao("j1") is None


@pytest.mark.parametrize("estado", ["cancelado", "concluido", "validando"])
def test_job_fora_de_analisando_nao_transcreve(estado: Estado, tmp_path: Path) -> None:
    transcritor = TranscritorFalso()

    executar(
        "j1",
        _repositorio(estado),
        TranscricoesEmMemoria({"j1": b"RIFF"}),
        transcritor,
        tmp_path,
    )

    assert transcritor.audios == []


def test_job_inexistente_nao_faz_nada(tmp_path: Path) -> None:
    transcritor = TranscritorFalso()

    executar(
        "nenhum", RepositorioEmMemoria(), TranscricoesEmMemoria(), transcritor, tmp_path
    )

    assert transcritor.audios == []


def test_modelo_do_dockerfile_esta_fixado_por_revisao_e_hash() -> None:
    dockerfile = (Path(__file__).parents[2] / "Dockerfile").read_text()
    modelo = dockerfile[dockerfile.index("AS modelo-whisper") :].split("\nFROM ")[0]
    alvo = dockerfile[dockerfile.index("AS transcricao") :].split("\nFROM ")[0]

    assert re.search(r"^ARG MODELO_REVISAO=[0-9a-f]{40}$", modelo, re.MULTILINE)
    assert re.search(r"^ARG MODELO_SHA256=[0-9a-f]{64}$", modelo, re.MULTILINE)
    assert "sha256sum -c" in modelo
    assert re.search(r"huggingface_hub==\d+\.\d+\.\d+", modelo)
    assert "--group transcricao" in alvo


def test_modelo_do_dockerfile_vem_antes_do_uv_sync() -> None:
    # Para uma mudança no uv.lock não baixar o modelo de novo (#211).
    dockerfile = (Path(__file__).parents[2] / "Dockerfile").read_text()
    alvo = dockerfile[dockerfile.index("AS transcricao") :].split("\nFROM ")[0]

    assert alvo.index("COPY --from=modelo-whisper") < alvo.index("RUN uv sync")
