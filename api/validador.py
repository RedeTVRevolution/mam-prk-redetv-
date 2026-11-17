"""Validador da quarentena: camadas 4 a 7 de Entradas hostis.

Devolve a cópia limpa, o proxy de reprodução e o SHA-256, ou levanta `Recusa`
com um código. A saída das ferramentas (stderr resumido) vai só para o log: a `Recusa`
a leva em `stderr`, e o Job de validação a registra; ela nunca chega ao Job nem ao cliente.
"""

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.cortes import (
    LIMIAR_PADRAO,
    TEMPO_LIMITE_S,
    CausaDaFalha,
    filtro_de_cortes,
    ler_cortes,
    resumir_stderr,
)
from api.modelo_do_job import CodigoDeFalha

MARCAS_PERMITIDAS = {b"isom", b"mp41", b"mp42", b"avc1"}
CODECS_VIDEO = {"h264", "hevc"}
LADO_CURTO_MAXIMO = 1080  # 1080p, também em retrato
LADO_LONGO_MAXIMO = 1920
SAR_MAXIMO = 4  # pixel de 1:4 a 4:1; fora disso a largura de exibição dispara
DURACAO_MINIMA_S = 1.0
DURACAO_MAXIMA_S = 4 * 3600.0
NOME_DO_AUDIO = "audio.wav"
DEMUXERS_ACEITOS = "mov,mp4,m4a,3gp,3g2,mj2"
TAXA_DO_AUDIO_HZ = 16_000
# Proxy 480p com pixel quadrado: a largura vem do aspecto de exibição (`dar` = pixels x SAR),
# não dos pixels de armazenamento. Sem SAR (ou 1:1) dá a mesma largura do antigo `-2:480`.
FILTRO_DO_PROXY = rf"scale=min(2*round(480*dar/2)\,{LADO_LONGO_MAXIMO}):480,setsar=1"
# HH:MM:SS:FF, ou HH:MM:SS;FF no drop-frame.
FORMATO_DO_TIMECODE = re.compile(r"([01]\d|2[0-3]):[0-5]\d:[0-5]\d[:;]\d{2}")


class Recusa(Exception):
    """A mensagem é só o código; `causa` e `stderr` são para o log."""

    def __init__(
        self,
        codigo: CodigoDeFalha,
        causa: CausaDaFalha | None = None,
        stderr: str = "",
    ) -> None:
        super().__init__(codigo)
        self.codigo = codigo
        self.causa = causa
        self.stderr = stderr


def _saiu_com_erro(r: subprocess.CompletedProcess[bytes]) -> Recusa:
    return Recusa(
        "arquivo_corrompido", "ffmpeg_saiu_com_erro", resumir_stderr(r.stderr)
    )


@dataclass(frozen=True)
class Aceito:
    copia_limpa: Path
    proxy: Path
    sha256: str
    duracao_s: float
    audio: Path | None = None
    cortes_ms: tuple[int, ...] = ()
    timecode_origem: str | None = None
    taxa_de_quadros: float | None = None


def _executar(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=TEMPO_LIMITE_S,
        )
    except subprocess.TimeoutExpired as e:
        # Estourar o tempo não é defeito do arquivo: pede novo envio, sem exportar.
        raise Recusa(
            "processamento_demorou_demais", "tempo_esgotado", resumir_stderr(e.stderr)
        ) from e


def _sha256(arquivo: Path) -> str:
    resumo = hashlib.sha256()
    with arquivo.open("rb") as f:
        while leitura := f.read(1 << 20):
            resumo.update(leitura)
    return resumo.hexdigest()


def _conferir_ftyp(entrada: Path) -> None:
    with entrada.open("rb") as f:
        cabecalho = f.read(12)
    if (
        len(cabecalho) < 12
        or cabecalho[4:8] != b"ftyp"
        or cabecalho[8:12] not in MARCAS_PERMITIDAS
    ):
        raise Recusa("formato_invalido")


def _sondar(entrada: Path) -> dict[str, Any]:
    # Só o leitor de MP4 e só arquivo local: nada de protocolos de rede.
    resultado = _executar(
        [
            "ffprobe", "-v", "error",
            "-protocol_whitelist", "file",
            "-f", DEMUXERS_ACEITOS,
            "-show_streams", "-show_format", "-of", "json",
            str(entrada),
        ]
    )  # fmt: skip
    if resultado.returncode != 0:
        raise _saiu_com_erro(resultado)
    try:
        sondagem: dict[str, Any] = json.loads(resultado.stdout)
    except ValueError:
        raise Recusa("arquivo_corrompido") from None
    return sondagem


def _duracao(sondagem: dict[str, Any]) -> float:
    try:
        return float(sondagem["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        raise Recusa("arquivo_corrompido") from None


def _conferir_faixas(sondagem: dict[str, Any]) -> None:
    faixas = sondagem.get("streams", [])
    videos = [f for f in faixas if f.get("codec_type") == "video"]
    audios = [f for f in faixas if f.get("codec_type") == "audio"]
    # Faixas de dados (timecode, metadados) passam: não são decodificadas nem copiadas.
    dados = [f for f in faixas if f.get("codec_type") == "data"]
    if (
        len(videos) != 1
        or len(audios) > 1
        or len(videos) + len(audios) + len(dados) != len(faixas)
    ):
        raise Recusa("codec_nao_suportado")
    if videos[0].get("codec_name") not in CODECS_VIDEO:
        raise Recusa("codec_nao_suportado")
    try:
        lados = sorted((int(videos[0]["width"]), int(videos[0]["height"])))
    except (KeyError, ValueError, TypeError):
        raise Recusa("arquivo_corrompido") from None
    if lados[0] > LADO_CURTO_MAXIMO or lados[1] > LADO_LONGO_MAXIMO:
        raise Recusa("codec_nao_suportado")
    _conferir_sar(videos[0].get("sample_aspect_ratio"))
    if audios and audios[0].get("codec_name") != "aac":
        raise Recusa("codec_nao_suportado")


def _conferir_sar(sar: object) -> None:
    """Recusa o SAR fora de 1/SAR_MAXIMO..SAR_MAXIMO. Ausente, `N/A` ou `0:1` = 1:1."""
    try:
        num, den = (int(x) for x in str(sar).split(":"))
    except ValueError:
        return
    if num > 0 and den > 0 and not 1 / SAR_MAXIMO <= num / den <= SAR_MAXIMO:
        raise Recusa("codec_nao_suportado")


def ler_timecode_origem(sondagem: dict[str, Any]) -> str | None:
    """O timecode inicial da faixa `tmcd`; `None` sem a faixa ou fora do formato."""
    for faixa in sondagem.get("streams", []):
        if faixa.get("codec_type") != "data":
            continue
        if faixa.get("codec_tag_string") != "tmcd":
            continue
        tags = faixa.get("tags")
        valor = tags.get("timecode") if isinstance(tags, dict) else None
        if isinstance(valor, str) and FORMATO_DO_TIMECODE.fullmatch(valor):
            return valor
    return None


def ler_taxa_de_quadros(sondagem: dict[str, Any]) -> float | None:
    """Quadros por segundo da faixa de vídeo; `None` sem taxa legível."""
    for faixa in sondagem.get("streams", []):
        if faixa.get("codec_type") != "video":
            continue
        valor = faixa.get("avg_frame_rate")
        if not isinstance(valor, str):
            return None
        try:
            numerador, _, denominador = valor.partition("/")
            taxa = float(numerador) / float(denominador or 1)
        except (ValueError, ZeroDivisionError):
            return None
        return taxa if taxa > 0 else None
    return None


def validar(
    entrada: Path, saida: Path, limiar_de_cortes: float = LIMIAR_PADRAO
) -> Aceito:
    _conferir_ftyp(entrada)
    sondagem = _sondar(entrada)
    _conferir_faixas(sondagem)
    duracao = _duracao(sondagem)
    if not DURACAO_MINIMA_S <= duracao <= DURACAO_MAXIMA_S:
        raise Recusa("duracao_excedida")

    saida.mkdir(parents=True, exist_ok=True)
    copia = saida / "copia_limpa.mp4"
    proxy = saida / "proxy.mp4"
    try:
        audio, cortes = _gerar_saidas(entrada, copia, proxy, sondagem, limiar_de_cortes)
    except Recusa:
        _apagar(copia, proxy, saida / NOME_DO_AUDIO)
        raise
    return Aceito(
        copia_limpa=copia,
        proxy=proxy,
        sha256=_sha256(entrada),
        duracao_s=duracao,
        audio=audio,
        cortes_ms=tuple(cortes),
        timecode_origem=ler_timecode_origem(sondagem),
        taxa_de_quadros=ler_taxa_de_quadros(sondagem),
    )


def _gerar_saidas(
    entrada: Path,
    copia: Path,
    proxy: Path,
    sondagem: dict[str, Any],
    limiar_de_cortes: float,
) -> tuple[Path | None, list[int]]:
    """Grava a cópia limpa, o proxy e o áudio; devolve o áudio (se houver) e os cortes.

    `Recusa` em qualquer falha; quem chama apaga o que já foi gravado.
    """
    comum = ["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file", "-y"]
    # Mesmo demuxer do ffprobe: o ffmpeg não escolhe o formato pelo conteúdo do original.
    entrada_mp4 = ["-f", DEMUXERS_ACEITOS]
    # Regravação sem recodificar: só vídeo e áudio, sem metadados nem capítulos.
    regravar = _executar(
        [
            *comum, *entrada_mp4, "-i", str(entrada),
            "-map", "0:v", "-map", "0:a?",
            "-c", "copy", "-map_metadata", "-1", "-map_chapters", "-1",
            "-movflags", "+faststart", str(copia),
        ]
    )  # fmt: skip
    if regravar.returncode != 0:
        raise _saiu_com_erro(regravar)
    # A cópia limpa leva as mesmas faixas da entrada: a sondagem dela basta.
    tem_audio = any(f.get("codec_type") == "audio" for f in sondagem.get("streams", []))
    audio = copia.parent / NOME_DO_AUDIO if tem_audio else None
    # Um ffmpeg decodifica o original uma vez e entrega as três saídas: o filtro de
    # cortes vê os quadros em resolução cheia, antes do `scale` do proxy.
    processo = _executar(
        [
            *comum, "-xerror", "-err_detect", "explode",
            *entrada_mp4, "-i", str(entrada),
            "-filter_complex",
            (
                "[0:v]split=2[para_cortes][para_proxy];"
                f"[para_cortes]{filtro_de_cortes(limiar_de_cortes)}[cortes];"
                f"[para_proxy]{FILTRO_DO_PROXY}[reduzido]"
            ),
            # veryfast: no clipe2, 41% mais rápido que o medium e SSIM de 0,986 contra 0,990.
            "-map", "[reduzido]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-map_metadata", "-1", "-map_chapters", "-1",
            "-movflags", "+faststart", str(proxy),
            *(
                ["-map", "0:a", "-ac", "1", "-ar", str(TAXA_DO_AUDIO_HZ),
                 "-c:a", "pcm_s16le", "-map_metadata", "-1", str(audio)]
                if audio
                else []
            ),
            "-map", "[cortes]", "-f", "null", "-",
        ]
    )  # fmt: skip
    if processo.returncode != 0:
        raise _saiu_com_erro(processo)
    return audio, ler_cortes(processo.stdout.decode(errors="replace"))


def _apagar(*gerados: Path | None) -> None:
    """Apaga o que a validação já gravou."""
    for arquivo in gerados:
        if arquivo is not None:
            arquivo.unlink(missing_ok=True)
