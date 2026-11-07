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
    quadros_por_s: int = 10,
    fonte: str = "testsrc",
    extra: tuple[str, ...] = (),
) -> Path:
    entradas = [
        "-f",
        "lavfi",
        "-i",
        f"{fonte}=size={tamanho}:rate={quadros_por_s}:duration={duracao}",
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
    assert aceito.cortes_ms == ()  # um plano só
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


def _faixas(arquivo: Path) -> list[str]:
    return [f["codec_type"] for f in _probe(arquivo)["streams"]]


def _padrao_da_redetv(destino: Path) -> Path:
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=s=854x480:d=2",
        "-f", "lavfi", "-i", "sine=d=2",
        "-c:v", "libx264", "-profile:v", "high", "-c:a", "aac",
        "-timecode", "01:00:00:00", str(destino),
    )  # fmt: skip
    return destino


def test_padrao_da_redetv_com_faixa_de_timecode_e_aceito(tmp_path: Path) -> None:
    entrada = _padrao_da_redetv(tmp_path / "video.mp4")
    assert _faixas(entrada) == ["video", "audio", "data"]

    aceito = validar(entrada, tmp_path / "saida")

    assert aceito.timecode_origem == "01:00:00:00"
    for arquivo in (aceito.copia_limpa, aceito.proxy):
        sondagem = _probe(arquivo)
        assert _faixas(arquivo) == ["video", "audio"]
        assert all("timecode" not in f.get("tags", {}) for f in sondagem["streams"])
        saida = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(arquivo)],
            check=True, capture_output=True, text=True,
        ).stdout  # fmt: skip
        assert "timecode" not in json.loads(saida)["format"].get("tags", {})


def test_mp4_sem_faixa_de_timecode_tem_timecode_origem_none(tmp_path: Path) -> None:
    aceito = validar(_gerar(tmp_path / "video.mp4"), tmp_path / "saida")

    assert aceito.timecode_origem is None


def test_video_com_faixa_de_dados_sem_audio_e_aceito(tmp_path: Path) -> None:
    entrada = _gerar(
        tmp_path / "video.mp4", audio=None, extra=("-timecode", "01:00:00:00")
    )
    assert _faixas(entrada) == ["video", "data"]

    aceito = validar(entrada, tmp_path / "saida")

    assert aceito.audio is None
    assert _faixas(aceito.copia_limpa) == ["video"]


def _faixa_de_timecode(valor: str | None) -> dict[str, Any]:
    tags = {} if valor is None else {"timecode": valor}
    return {
        "streams": [
            {"codec_type": "video"},
            {"codec_type": "data", "codec_tag_string": "tmcd", "tags": tags},
        ]
    }


@pytest.mark.parametrize(
    "valor", ["abc", "25:00:00", "", "01:00:00:0", "01:00:00:000", None]
)
def test_timecode_fora_do_formato_vira_none(valor: str | None) -> None:
    assert validador.ler_timecode_origem(_faixa_de_timecode(valor)) is None


@pytest.mark.parametrize("valor", ["01:00:00;00", "01:00:00:00"])
def test_timecode_no_formato_passa_como_veio(valor: str) -> None:
    assert validador.ler_timecode_origem(_faixa_de_timecode(valor)) == valor


@pytest.mark.parametrize(
    ("taxa", "esperada"),
    [
        ("30000/1001", pytest.approx(29.97, abs=0.001)),
        ("25/1", 25.0),
        ("0/0", None),
        ("abc", None),
        ("30/0", None),
        (None, None),
    ],
)
def test_taxa_de_quadros_vem_da_faixa_de_video(taxa: str | None, esperada: Any) -> None:
    faixa = {"codec_type": "video"} if taxa is None else {
        "codec_type": "video", "avg_frame_rate": taxa
    }  # fmt: skip
    assert validador.ler_taxa_de_quadros({"streams": [faixa]}) == esperada


def test_taxa_de_quadros_do_arquivo_chega_ao_aceito(tmp_path: Path) -> None:
    aceito = validar(_gerar(tmp_path / "video.mp4"), tmp_path / "saida")
    assert aceito.taxa_de_quadros == 10.0


def test_duas_faixas_de_audio_com_uma_de_dados_e_recusada(tmp_path: Path) -> None:
    base = _gerar(tmp_path / "base.mp4", extra=("-timecode", "01:00:00:00"))
    entrada = tmp_path / "video.mp4"
    _ffmpeg(
        "-i", str(base), "-i", str(base),
        "-map", "0:v", "-map", "0:a", "-map", "1:a", "-c", "copy",
        "-timecode", "01:00:00:00", str(entrada),
    )  # fmt: skip
    assert sorted(_faixas(entrada)) == ["audio", "audio", "data", "video"]

    assert _recusa(entrada, tmp_path) == "codec_nao_suportado"


def test_duas_faixas_de_audio_e_recusada(tmp_path: Path) -> None:
    base = _gerar(tmp_path / "base.mp4")
    entrada = tmp_path / "video.mp4"
    _ffmpeg(
        "-i", str(base), "-i", str(base),
        "-map", "0", "-map", "1:a", "-c", "copy", str(entrada),
    )  # fmt: skip

    assert _recusa(entrada, tmp_path) == "codec_nao_suportado"


def test_faixa_de_legenda_e_recusada(tmp_path: Path) -> None:
    base = _gerar(tmp_path / "base.mp4")
    legenda = tmp_path / "l.srt"
    legenda.write_text("1\n00:00:00,000 --> 00:00:01,000\noi\n")
    entrada = tmp_path / "video.mp4"
    _ffmpeg(
        "-i", str(base), "-i", str(legenda),
        "-map", "0", "-map", "1", "-c", "copy", "-c:s", "mov_text", str(entrada),
    )  # fmt: skip
    assert "subtitle" in _faixas(entrada)

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


def _programa_longo(destino: Path, duracao: float) -> Path:
    # Resolução mínima, 1 quadro por segundo e tela lisa e sem áudio: a duração é o que importa.
    return _gerar(
        destino,
        fonte="color",
        audio=None,
        duracao=duracao,
        tamanho="64x64",
        quadros_por_s=1,
        extra=("-g", "600", "-preset", "ultrafast"),
    )


def test_programa_de_4h_e_aceito(tmp_path: Path) -> None:
    entrada = _programa_longo(tmp_path / "video.mp4", validador.DURACAO_MAXIMA_S)

    assert validar(entrada, tmp_path / "saida").duracao_s == pytest.approx(14400, abs=1)


def test_mais_de_4h_e_recusado(tmp_path: Path) -> None:
    entrada = _programa_longo(tmp_path / "video.mp4", validador.DURACAO_MAXIMA_S + 1)

    assert _recusa(entrada, tmp_path) == "duracao_excedida"


def test_o_limite_e_de_4h() -> None:
    assert validador.DURACAO_MAXIMA_S == 14_400


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


def test_os_dois_ffmpeg_que_leem_o_original_forcam_o_demuxer_do_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entrada = _padrao_da_redetv(tmp_path / "video.mp4")
    assert "data" in _faixas(entrada)  # a trilha tmcd da RedeTV
    comandos: list[list[str]] = []
    executar = validador._executar

    def espiar(args: list[str]) -> subprocess.CompletedProcess[bytes]:
        comandos.append(args)
        return executar(args)

    monkeypatch.setattr(validador, "_executar", espiar)

    aceito = validar(entrada, tmp_path / "saida")

    assert aceito.timecode_origem == "01:00:00:00"
    lendo_o_original = [c for c in comandos if str(entrada) in c]
    assert {c[0] for c in lendo_o_original} == {"ffprobe", "ffmpeg"}
    assert len([c for c in lendo_o_original if c[0] == "ffmpeg"]) == 2
    for comando in lendo_o_original:
        assert comando[comando.index("-f") + 1] == "mov,mp4,m4a,3gp,3g2,mj2"
        if comando[0] == "ffmpeg":
            assert comando.index("-f") < comando.index("-i")
