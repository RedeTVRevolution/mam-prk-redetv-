"""Formato guardado e adaptador do Florence-2, sem modelo real."""

import sys
from types import ModuleType
from typing import Any

import pytest
from PIL import Image

from api import florence
from api.dispositivo import DispositivoIndisponivel
from api.florence import (
    NOME_DO_MODELO,
    REVISAO,
    DetectorFlorence,
    ObjetoDetectado,
    RegiaoLegendada,
)
from api.leitura_da_tela import Caixa


class ModeloFalso:
    """Devolve, por tarefa, o que o `post_process_generation` devolveria (pixels)."""

    def __init__(self) -> None:
        self.chamadas: list[str] = []

    def __call__(self, imagem: Image.Image, tarefa: str) -> dict[str, Any]:
        self.chamadas.append(tarefa)
        if tarefa == "<OD>":
            return {"bboxes": [[10.0, 20.0, 110.0, 70.0]], "labels": ["car"]}
        return {"bboxes": [[0.0, 0.0, 200.0, 100.0]], "labels": ["a red car"]}


def test_o_nome_do_modelo_traz_a_revisao_fixada() -> None:
    assert NOME_DO_MODELO == f"florence-community/Florence-2-large@{REVISAO}"
    assert REVISAO == "4271c66b88cdbc05735372ec13b2360108de5317"


def test_detectar_normaliza_as_caixas_pelo_tamanho_do_quadro() -> None:
    detector = DetectorFlorence(ModeloFalso())

    objetos, regioes = detector.detectar(Image.new("RGB", (200, 100)))

    assert objetos == [
        ObjetoDetectado(
            rotulo="car", caixa=Caixa(x=0.05, y=0.2, largura=0.5, altura=0.5)
        )
    ]
    assert regioes == [
        RegiaoLegendada(
            legenda="a red car", caixa=Caixa(x=0.0, y=0.0, largura=1.0, altura=1.0)
        )
    ]


def test_detectar_roda_as_duas_tarefas() -> None:
    modelo = ModeloFalso()
    DetectorFlorence(modelo).detectar(Image.new("RGB", (200, 100)))
    assert modelo.chamadas == ["<OD>", "<DENSE_REGION_CAPTION>"]


def test_rotulo_vazio_e_descartado() -> None:
    class Vazio:
        def __call__(self, imagem: Image.Image, tarefa: str) -> dict[str, Any]:
            return {"bboxes": [[0, 0, 10, 10]], "labels": ["  "]}

    objetos, regioes = DetectorFlorence(Vazio()).detectar(Image.new("RGB", (20, 20)))
    assert objetos == [] and regioes == []


@pytest.fixture
def modulos_falsos(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """`torch` e `transformers` falsos: guardam como o modelo foi carregado."""
    carregados: list[Any] = []
    torch: Any = ModuleType("torch")
    cuda: Any = ModuleType("torch.cuda")
    cuda.device_count = lambda: 1
    torch.cuda = cuda
    torch.float16 = "f16"
    torch.float32 = "f32"
    monkeypatch.setitem(sys.modules, "torch", torch)
    transformers = ModuleType("transformers")

    class _Fabrica:
        @staticmethod
        def from_pretrained(pasta: str, **opcoes: Any) -> Any:
            carregados.append((pasta, opcoes))
            return _Objeto()

    class _Objeto:
        def to(self, *args: Any, **kwargs: Any) -> "_Objeto":
            carregados.append(("to", args, kwargs))
            return self

        def eval(self) -> "_Objeto":
            return self

    transformers.AutoProcessor = _Fabrica  # type: ignore[attr-defined]
    transformers.Florence2ForConditionalGeneration = _Fabrica  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    return carregados


def test_gpu_carrega_em_float16_sem_codigo_remoto(
    modulos_falsos: list[Any],
) -> None:
    florence._carregar("/modelo", "gpu")

    opcoes = [o for c in modulos_falsos if c[0] == "/modelo" for o in [c[1]]]
    assert len(opcoes) == 2
    assert all(o["local_files_only"] for o in opcoes)
    assert not any("trust_remote_code" in o for o in opcoes)
    assert {"torch_dtype": "f16"}.items() <= opcoes[1].items()
    assert [c[1] for c in modulos_falsos if c[0] == "to"] == [("cuda",)]


def test_gpu_sem_gpu_falha_sem_cair_para_a_cpu(modulos_falsos: list[Any]) -> None:
    with pytest.raises(DispositivoIndisponivel):
        florence._carregar("/modelo", "gpu", gpus=lambda: 0)
    assert modulos_falsos == []


def test_da_pasta_usa_o_dispositivo_da_configuracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISPOSITIVO", "cpu")
    visto: list[Any] = []
    DetectorFlorence.da_pasta(
        "/modelo", carregar=lambda pasta, disp: visto.append((pasta, disp))
    )
    assert visto == [("/modelo", "cpu")]
