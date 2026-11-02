"""O modo de teste dos Jobs com GPU (#238): dispositivo e resultado, sem modelo real."""

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from api import ocr_job, teste_dos_jobs, transcricao_job
from api.dispositivo import DispositivoIndisponivel
from api.paddle import LeitorPaddle
from api.teste_dos_jobs import (
    SAIDA_OK,
    SAIDA_RESULTADO_ERRADO,
    SAIDA_SEM_GPU,
    ativo,
    normalizar,
)
from api.teste_dos_jobs import (
    testar_ocr as _ocr,
)
from api.teste_dos_jobs import (
    testar_transcricao as _transcricao,
)
from api.transcricao import Palavra, Transcricao
from api.whisper import TranscritorFasterWhisper

RAIZ = Path(__file__).parents[2]
AMBIENTE = {"PASTA_DO_MODELO": "/modelo", "PASTA_DOS_MODELOS": "/modelos"}


def test_so_o_valor_1_liga_o_modo_de_teste() -> None:
    assert ativo({"MODO_TESTE": "1"})
    assert not ativo({})
    assert not ativo({"MODO_TESTE": "0"})
    assert not ativo({"MODO_TESTE": "sim"})


def test_normalizar_tira_acento_caixa_e_pontuacao() -> None:
    assert normalizar(" Bom dia, São Paulo! ") == "bom dia sao paulo"


class TranscritorFalso:
    def __init__(self, texto: str) -> None:
        self.texto = texto

    def transcrever(self, audio: Path) -> Transcricao:
        assert audio == Path("/amostras/fala.wav")
        palavras = [
            Palavra(texto=t, inicio_s=i, fim_s=i + 0.5)
            for i, t in enumerate(self.texto.split())
        ]
        return Transcricao(modelo="m", idioma="pt", palavras=palavras)


def _transcritor(
    monkeypatch: pytest.MonkeyPatch, texto: str | Exception
) -> list[tuple[str, Any]]:
    criados: list[tuple[str, Any]] = []

    def da_pasta(pasta: str, dispositivo: Any = None) -> TranscritorFalso:
        criados.append((pasta, dispositivo))
        if isinstance(texto, Exception):
            raise texto
        return TranscritorFalso(texto)

    monkeypatch.setattr(TranscritorFasterWhisper, "da_pasta", da_pasta)
    return criados


def test_transcricao_na_gpu_com_a_frase_certa_passa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    criados = _transcritor(monkeypatch, "Bom dia, a todos.")

    assert _transcricao("gpu", ambiente=AMBIENTE) == SAIDA_OK
    assert criados == [("/modelo", "gpu")]


def test_transcricao_com_texto_diferente_e_resultado_errado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _transcritor(monkeypatch, "boa noite")

    assert _transcricao("gpu", ambiente=AMBIENTE) == SAIDA_RESULTADO_ERRADO


def test_transcricao_sem_gpu_na_instancia_diz_que_a_gpu_nao_funcionou(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _transcritor(monkeypatch, DispositivoIndisponivel("nenhuma GPU"))

    assert _transcricao("gpu", ambiente=AMBIENTE) == SAIDA_SEM_GPU


def test_o_teste_da_publicacao_exige_gpu_e_o_da_construcao_roda_em_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    criados = _transcritor(monkeypatch, "bom dia")

    assert _transcricao("cpu", ambiente=AMBIENTE) == SAIDA_SEM_GPU
    assert criados == []
    assert _transcricao("cpu", exigir_gpu=False, ambiente=AMBIENTE) == SAIDA_OK
    assert criados == [("/modelo", "cpu")]


def test_o_dispositivo_vem_da_variavel_quando_nao_e_dado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    criados = _transcritor(monkeypatch, "bom dia")

    assert _transcricao(ambiente={**AMBIENTE, "DISPOSITIVO": "gpu"}) == SAIDA_OK
    assert criados == [("/modelo", "gpu")]


def _leitor(monkeypatch: pytest.MonkeyPatch, textos: list[str]) -> None:
    class Leitor:
        def ler(self, quadro: Path) -> list[Any]:
            assert quadro == Path("/amostras/quadro.png")
            return [SimpleNamespace(texto=t) for t in textos]

    monkeypatch.setattr(
        LeitorPaddle, "da_pasta", lambda pasta, dispositivo=None: Leitor()
    )


def test_ocr_le_redetv_no_quadro_da_amostra(monkeypatch: pytest.MonkeyPatch) -> None:
    _leitor(monkeypatch, ["REDETV"])

    assert _ocr("gpu", ambiente=AMBIENTE) == SAIDA_OK


def test_ocr_que_le_outra_coisa_e_resultado_errado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _leitor(monkeypatch, ["RED3TV"])

    assert _ocr("gpu", ambiente=AMBIENTE) == SAIDA_RESULTADO_ERRADO


def test_a_pasta_das_amostras_vem_da_configuracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    visto: list[Path] = []

    class Leitor:
        def ler(self, quadro: Path) -> list[Any]:
            visto.append(quadro)
            return [SimpleNamespace(texto="REDETV")]

    monkeypatch.setattr(LeitorPaddle, "da_pasta", lambda p, d=None: Leitor())

    _ocr("gpu", ambiente={**AMBIENTE, "AMOSTRAS": "/outra"})

    assert visto == [Path("/outra/quadro.png")]


@pytest.mark.parametrize(
    ("modulo", "funcao"),
    [(transcricao_job, "testar_transcricao"), (ocr_job, "testar_ocr")],
)
def test_main_em_modo_de_teste_sai_com_o_codigo_do_teste_sem_tocar_na_nuvem(
    modulo: Any, funcao: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODO_TESTE", "1")
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("JOB_ID", raising=False)
    monkeypatch.setattr(teste_dos_jobs, funcao, lambda: SAIDA_RESULTADO_ERRADO)

    with pytest.raises(SystemExit) as saida:
        modulo.main()

    assert saida.value.code == SAIDA_RESULTADO_ERRADO


def test_a_amostra_falada_na_construcao_e_a_frase_que_o_teste_espera() -> None:
    dockerfile = (RAIZ / "Dockerfile").read_text()

    falado = re.search(r'espeak-ng [^\n]*-w /amostras/fala.wav "([^"]+)"', dockerfile)
    assert falado
    assert normalizar(teste_dos_jobs.FRASE_FALADA) in normalizar(falado.group(1))
    assert f"putText(q, '{teste_dos_jobs.TEXTO_DO_QUADRO}'" in dockerfile
