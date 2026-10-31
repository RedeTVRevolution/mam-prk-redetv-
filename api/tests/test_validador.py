import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from api import validador
from api.jobs import CodigoDeFalha
from api.validador import Recusa, validar

# Sem ffmpeg na máquina (o CI), os testes rodam na imagem do Job: make testar-na-imagem.
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *args],
        check=True,
        capture_output=True,
    )


def _gerar(
    destino: Path,
    *,
    duracao: float = 2,
    video: str = "libx264",
    audio: str | None = "aac",
    tamanho: str = "320x240",
    extra: tuple[str, ...] = (),
) -> Path:
    entradas = [
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={tamanho}:rate=10:duration={duracao}",
    ]
    mapas = ["-map", "0:v"]
    codec_audio: list[str] = []
    if audio:
        entradas += ["-f", "lavfi", "-i", f"sine=duration={duracao}"]
        mapas += ["-map", "1:a"]
        codec_audio = ["-c:a", audio]
    _ffmpeg(*entradas, *mapas, "-c:v", video, *codec_audio, *extra, str(destino))
    return destino


def _probe(arquivo: Path) -> dict[str, list[dict[str, Any]]]:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(arquivo)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(saida)  # type: ignore[no-any-return]


def _recusa(arquivo: Path, tmp_path: Path) -> CodigoDeFalha:
    with pytest.raises(Recusa) as erro:
        validar(arquivo, tmp_path / "saida")
    return erro.value.codigo


def test_mov_renomeado_para_mp4_e_recusado(tmp_path: Path) -> None:
    mov = _gerar(tmp_path / "video.mov")
    mp4 = mov.rename(tmp_path / "video.mp4")

    assert _recusa(mp4, tmp_path) == "formato_invalido"


def test_h264_valido_gera_copia_limpa_proxy_e_sha256(tmp_path: Path) -> None:
    entrada = _gerar(
        tmp_path / "video.mp4",
        extra=("-metadata", "title=segredo", "-movflags", "+faststart"),
    )

    aceito = validar(entrada, tmp_path / "saida")

    assert aceito.sha256 == hashlib.sha256(entrada.read_bytes()).hexdigest()
    tipos = [f["codec_type"] for f in _probe(aceito.copia_limpa)["streams"]]
    assert sorted(tipos) == ["audio", "video"]
    assert b"segredo" not in aceito.copia_limpa.read_bytes()


def test_h265_valido_gera_proxy_480p_h264_com_faststart(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", video="libx265", extra=("-tag:v", "hvc1"))

    aceito = validar(entrada, tmp_path / "saida")

    video = next(
        f for f in _probe(aceito.proxy)["streams"] if f["codec_type"] == "video"
    )
    assert video["codec_name"] == "h264"
    assert video["height"] == 480
    audio = next(
        f for f in _probe(aceito.proxy)["streams"] if f["codec_type"] == "audio"
    )
    assert audio["codec_name"] == "aac"
    dados = aceito.proxy.read_bytes()
    assert dados.index(b"moov") < dados.index(b"mdat")
    copia = next(
        f for f in _probe(aceito.copia_limpa)["streams"] if f["codec_type"] == "video"
    )
    assert copia["codec_name"] == "hevc"


def test_arquivo_truncado_e_corrompido(tmp_path: Path) -> None:
    inteiro = _gerar(tmp_path / "inteiro.mp4", extra=("-movflags", "+faststart"))
    truncado = tmp_path / "truncado.mp4"
    truncado.write_bytes(inteiro.read_bytes()[:-3000])

    assert _recusa(truncado, tmp_path) == "arquivo_corrompido"


def test_arquivo_ilegivel_com_ftyp_e_corrompido(tmp_path: Path) -> None:
    lixo = tmp_path / "lixo.mp4"
    lixo.write_bytes(
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\xff" * 500
    )

    assert _recusa(lixo, tmp_path) == "arquivo_corrompido"


def test_codec_de_audio_fora_da_lista_e_recusado(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", audio="ac3")

    assert _recusa(entrada, tmp_path) == "codec_nao_suportado"


def test_codec_de_video_fora_da_lista_e_recusado(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", video="mpeg4")

    assert _recusa(entrada, tmp_path) == "codec_nao_suportado"


def test_acima_de_1080p_e_recusado(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", tamanho="2560x1440", duracao=1)

    assert _recusa(entrada, tmp_path) == "codec_nao_suportado"


def test_faixa_de_dados_extra_e_recusada(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", extra=("-timecode", "01:00:00:00"))
    assert "data" in [f["codec_type"] for f in _probe(entrada)["streams"]]

    assert _recusa(entrada, tmp_path) == "codec_nao_suportado"


def test_faixa_de_video_duplicada_e_recusada(tmp_path: Path) -> None:
    base = _gerar(tmp_path / "base.mp4")
    entrada = tmp_path / "video.mp4"
    _ffmpeg(
        "-i",
        str(base),
        "-i",
        str(base),
        "-map",
        "0",
        "-map",
        "1:v",
        "-c",
        "copy",
        str(entrada),
    )

    assert _recusa(entrada, tmp_path) == "codec_nao_suportado"


def test_menos_de_1s_e_recusado(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", duracao=0.5)

    assert _recusa(entrada, tmp_path) == "duracao_excedida"


def test_mais_de_10min_e_recusado(tmp_path: Path) -> None:
    entrada = _gerar(
        tmp_path / "video.mp4",
        duracao=601,
        tamanho="64x64",
        extra=("-g", "600", "-preset", "ultrafast"),
    )

    assert _recusa(entrada, tmp_path) == "duracao_excedida"


def test_recusa_devolve_so_o_codigo(tmp_path: Path) -> None:
    truncado = tmp_path / "t.mp4"
    truncado.write_bytes(_gerar(tmp_path / "i.mp4").read_bytes()[:-3000])

    with pytest.raises(Recusa) as erro:
        validar(truncado, tmp_path / "saida")

    assert str(erro.value) == "arquivo_corrompido"
    assert erro.value.__cause__ is None


def test_video_em_retrato_1080p_e_aceito(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", tamanho="1080x1920", duracao=1)

    assert validar(entrada, tmp_path / "saida").copia_limpa.exists()


def test_video_sem_audio_e_aceito(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", audio=None)

    aceito = validar(entrada, tmp_path / "saida")

    assert [f["codec_type"] for f in _probe(aceito.copia_limpa)["streams"]] == ["video"]


def test_corrupcao_no_meio_do_arquivo_e_recusada(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", duracao=5, tamanho="640x480")
    dados = bytearray(entrada.read_bytes())
    meio = len(dados) // 2
    dados[meio : meio + 400] = b"\xff" * 400
    entrada.write_bytes(bytes(dados))

    assert _recusa(entrada, tmp_path) == "arquivo_corrompido"


def test_audio_sai_da_copia_limpa_em_mono_16khz_ao_lado_dela(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", extra=("-ac", "2", "-ar", "44100"))

    aceito = validar(entrada, tmp_path / "saida")

    assert aceito.audio == aceito.copia_limpa.parent / "audio.wav"
    (faixa,) = _probe(aceito.audio)["streams"]
    assert faixa["codec_type"] == "audio"
    assert faixa["channels"] == 1
    assert faixa["sample_rate"] == "16000"
    assert float(faixa["duration"]) == pytest.approx(2, abs=0.1)


def test_video_sem_audio_nao_gera_arquivo_de_audio(tmp_path: Path) -> None:
    entrada = _gerar(tmp_path / "video.mp4", audio=None)

    aceito = validar(entrada, tmp_path / "saida")

    assert aceito.audio is None
    assert not (tmp_path / "saida" / "audio.wav").exists()


def test_falha_ao_separar_o_audio_recusa_e_apaga_a_copia_e_o_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entrada = _gerar(tmp_path / "video.mp4")
    monkeypatch.setattr(validador, "_separar_audio", lambda copia, saida: None)

    assert _recusa(entrada, tmp_path) == "arquivo_corrompido"
    assert list((tmp_path / "saida").iterdir()) == []
