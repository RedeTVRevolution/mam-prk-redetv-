"""Falha da validação guarda a causa (#676): tempo esgotado x ffmpeg com erro.

O ffmpeg é trocado por um script na frente do PATH: nos cortes (filtro `scene`) ele estoura
o tempo ou sai com erro; nas outras chamadas passa para o ffmpeg de verdade.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from api import cortes, validador
from api.cortes import DeteccaoFalhou, detectar_cortes
from api.validador import Recusa, validar

COM_FFMPEG = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sem ffmpeg")
REAL = shutil.which("ffmpeg")

COMPORTAMENTOS = {
    "tempo_esgotado": "sleep 5",
    "ffmpeg_saiu_com_erro": "echo 'Invalid data found' >&2; exit 1",
}


def _trocar_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, comportamento: str, so_cortes: bool
) -> None:
    pasta = tmp_path / "bin"
    pasta.mkdir()
    gatilho = '[[ "$*" == *scene* ]]' if so_cortes else "true"
    falso = pasta / "ffmpeg"
    falso.write_text(
        f'#!/bin/bash\nif {gatilho}; then {comportamento}; fi\nexec {REAL or "false"} "$@"\n'
    )
    falso.chmod(0o755)
    monkeypatch.setenv(
        "PATH", f"{pasta}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"
    )
    # Mesma constante nos dois módulos: um segundo basta para o teste.
    monkeypatch.setattr(cortes, "TEMPO_LIMITE_S", 1)
    monkeypatch.setattr(validador, "TEMPO_LIMITE_S", 1)


def _mp4(destino: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=2",
            "-f", "lavfi", "-i", "sine=duration=2",
            "-c:v", "libx264", "-c:a", "aac", str(destino),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return destino


def test_o_tempo_limite_e_uma_constante_so() -> None:
    assert vars(validador)["TEMPO_LIMITE_S"] == cortes.TEMPO_LIMITE_S == 7200


@pytest.mark.parametrize("causa", COMPORTAMENTOS)
def test_cortes_levanta_com_a_causa_na_mensagem(
    causa: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _trocar_ffmpeg(monkeypatch, tmp_path, COMPORTAMENTOS[causa], so_cortes=False)
    with pytest.raises(DeteccaoFalhou) as erro:
        detectar_cortes(tmp_path / "v.mp4")
    assert erro.value.causa == causa
    assert causa in str(erro.value)
    if causa == "ffmpeg_saiu_com_erro":
        assert "Invalid data found" in erro.value.stderr
    else:
        assert isinstance(erro.value.__cause__, subprocess.TimeoutExpired)


@COM_FFMPEG
@pytest.mark.parametrize(
    ("causa", "codigo"),
    [
        ("tempo_esgotado", "processamento_demorou_demais"),
        ("ffmpeg_saiu_com_erro", "arquivo_corrompido"),
    ],
)
@pytest.mark.parametrize("so_cortes", [True, False])
def test_validador_distingue_tempo_esgotado_de_ffmpeg_com_erro(
    causa: str,
    codigo: str,
    so_cortes: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = _mp4(tmp_path / "v.mp4")
    _trocar_ffmpeg(monkeypatch, tmp_path, COMPORTAMENTOS[causa], so_cortes)

    with pytest.raises(Recusa) as erro:
        validar(video, tmp_path / "saida")

    assert (erro.value.codigo, erro.value.causa) == (codigo, causa)
    # A mensagem segue sendo só o código: o stderr vai para o log, não para quem captura a exceção.
    assert str(erro.value) == codigo
    assert not (tmp_path / "saida" / "copia_limpa.mp4").exists()
