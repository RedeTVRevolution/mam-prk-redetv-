"""O dispositivo da configuração chega ao faster-whisper e ao PaddleOCR, sem modelo real."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from api import paddle, whisper
from api.dispositivo import DispositivoIndisponivel, ler_dispositivo


@pytest.fixture
def faster_whisper_falso(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    criados: list[dict[str, Any]] = []
    modulo = ModuleType("faster_whisper")
    modulo.WhisperModel = lambda pasta, **opcoes: criados.append(  # type: ignore[attr-defined]
        {"pasta": pasta, **opcoes}
    )
    monkeypatch.setitem(sys.modules, "faster_whisper", modulo)
    return criados


@pytest.fixture
def paddleocr_falso(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    criados: list[dict[str, Any]] = []
    modulo = ModuleType("paddleocr")
    modulo.PaddleOCR = lambda **opcoes: criados.append(opcoes)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", modulo)
    return criados


def test_o_padrao_e_cpu() -> None:
    assert ler_dispositivo({}) == "cpu"
    assert ler_dispositivo({"DISPOSITIVO": ""}) == "cpu"


def test_le_gpu_e_cpu_da_configuracao() -> None:
    assert ler_dispositivo({"DISPOSITIVO": "gpu"}) == "gpu"
    assert ler_dispositivo({"DISPOSITIVO": " CPU "}) == "cpu"


def test_valor_desconhecido_e_erro_claro() -> None:
    with pytest.raises(ValueError, match="'cpu' ou 'gpu'"):
        ler_dispositivo({"DISPOSITIVO": "tpu"})


def test_whisper_em_cpu_por_padrao_mantem_int8(
    faster_whisper_falso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISPOSITIVO", raising=False)

    whisper.TranscritorFasterWhisper.da_pasta("/modelo")

    assert faster_whisper_falso == [
        {
            "pasta": "/modelo",
            "device": "cpu",
            "compute_type": "int8",
            "local_files_only": True,
        }
    ]


def test_whisper_em_gpu_usa_cuda_e_float16(
    faster_whisper_falso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DISPOSITIVO", "gpu")
    monkeypatch.setattr(whisper, "_gpus", lambda: 1)

    whisper.TranscritorFasterWhisper.da_pasta("/modelo")

    (criado,) = faster_whisper_falso
    assert (criado["device"], criado["compute_type"]) == ("cuda", "float16")


def test_whisper_com_gpu_sem_gpu_falha_sem_cair_para_a_cpu(
    faster_whisper_falso: list[dict[str, Any]],
) -> None:
    with pytest.raises(DispositivoIndisponivel, match="nenhuma GPU"):
        whisper._carregar("/modelo", "gpu", gpus=lambda: 0)

    assert faster_whisper_falso == []


def test_whisper_pede_a_deteccao_de_voz_nas_duas_versoes(tmp_path: Path) -> None:
    chamadas: list[dict[str, Any]] = []

    class Modelo:
        def transcribe(self, audio: str, **opcoes: Any) -> tuple[Any, Any]:
            chamadas.append(opcoes)
            return iter([SimpleNamespace(words=None)]), None

    whisper.TranscritorFasterWhisper(Modelo()).transcrever(tmp_path / "a.wav")

    assert chamadas[0]["vad_filter"] is True
    assert chamadas[0]["vad_parameters"] == whisper.VAD_PARAMETROS
    assert chamadas[0]["word_timestamps"] is True


def test_paddle_em_cpu_por_padrao(
    paddleocr_falso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISPOSITIVO", raising=False)

    paddle.LeitorPaddle.da_pasta("/modelos")

    (criado,) = paddleocr_falso
    assert criado["device"] == "cpu"
    assert criado["text_detection_model_dir"] == str(Path("/modelos") / paddle.DETECTOR)


def test_paddle_em_gpu_pede_a_primeira_gpu(
    paddleocr_falso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DISPOSITIVO", "gpu")
    monkeypatch.setattr(paddle, "_gpus", lambda: 1)

    paddle.LeitorPaddle.da_pasta("/modelos")

    (criado,) = paddleocr_falso
    assert criado["device"] == "gpu:0"


def test_paddle_com_gpu_sem_gpu_falha_sem_cair_para_a_cpu(
    paddleocr_falso: list[dict[str, Any]],
) -> None:
    with pytest.raises(DispositivoIndisponivel, match="nenhuma GPU"):
        paddle._carregar("/modelos", "gpu", gpus=lambda: 0)

    assert paddleocr_falso == []


def test_o_dispositivo_dado_vale_mais_que_a_variavel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISPOSITIVO", "gpu")
    recebidos: list[Any] = []

    paddle.LeitorPaddle.da_pasta(
        "/m", "cpu", carregar=lambda *args: recebidos.append(args)
    )

    assert recebidos == [("/m", "cpu")]


RAIZ = Path(__file__).parents[2]


def _alvo(dockerfile: str, nome: str) -> str:
    return dockerfile[dockerfile.index(f"AS {nome}\n") :].split("\nFROM ")[0]


def test_alvos_com_gpu_reaproveitam_os_modelos_fixados_dos_alvos_de_cpu() -> None:
    dockerfile = (RAIZ / "Dockerfile").read_text()

    transcricao = _alvo(dockerfile, "transcricao-gpu")
    assert "FROM transcricao-base AS transcricao-gpu" in dockerfile
    assert "--group transcricao-gpu" in transcricao
    assert "DISPOSITIVO=gpu" in transcricao
    assert (
        "resolve/" not in transcricao
    )  # sem baixar de novo: o modelo vem do alvo base

    ocr = _alvo(dockerfile, "ocr-gpu")
    # Os mesmos modelos fixados do alvo de CPU, pelo mesmo script (o detector `server`).
    assert 'RUN baixar-modelos-ocr "$DETECTOR"' in ocr
    assert "--group ocr-gpu" in ocr
    assert "resolve/" not in ocr
    assert "DISPOSITIVO=gpu" in ocr


def test_paddle_usa_o_detector_da_imagem(
    paddleocr_falso: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DETECTOR", "PP-OCRv5_mobile_det")

    paddle.LeitorPaddle.da_pasta("/modelos")

    (criado,) = paddleocr_falso
    assert criado["text_detection_model_name"] == "PP-OCRv5_mobile_det"
    assert criado["text_detection_model_dir"] == str(
        Path("/modelos") / "PP-OCRv5_mobile_det"
    )
    assert paddle.nome_do_modelo() == f"PP-OCRv5_mobile_det+{paddle.RECONHECEDOR}"


def test_paddle_sem_detector_na_imagem_usa_o_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DETECTOR", raising=False)

    assert paddle.detector() == "PP-OCRv5_server_det"
    assert paddle.nome_do_modelo() == f"PP-OCRv5_server_det+{paddle.RECONHECEDOR}"


def test_paddle_com_detector_desconhecido_falha_com_mensagem_clara(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR", "outro")

    with pytest.raises(ValueError, match="DETECTOR inválido"):
        paddle.detector()
