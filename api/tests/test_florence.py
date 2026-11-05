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
    Configuracao,
    DetectorFlorence,
    ObjetoDetectado,
    RegiaoLegendada,
    ler_configuracao,
)
from api.leitura_da_tela import Caixa


class ModeloFalso:
    """Devolve, por tarefa, o que o `post_process_generation` devolveria (pixels)."""

    def __init__(self) -> None:
        self.chamadas: list[str] = []

    def __call__(self, imagens: list[Image.Image], tarefa: str) -> list[dict[str, Any]]:
        self.chamadas.append(tarefa)
        if tarefa == "<OD>":
            um = {"bboxes": [[10.0, 20.0, 110.0, 70.0]], "labels": ["car"]}
        else:
            um = {"bboxes": [[0.0, 0.0, 200.0, 100.0]], "labels": ["a red car"]}
        return [um for _ in imagens]


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
        def __call__(
            self, imagens: list[Image.Image], tarefa: str
        ) -> list[dict[str, Any]]:
            return [{"bboxes": [[0, 0, 10, 10]], "labels": ["  "]} for _ in imagens]

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
        "/modelo",
        carregar=lambda pasta, disp, **_: visto.append((pasta, disp)),
    )
    assert visto == [("/modelo", "cpu")]


def test_lote_roda_uma_geracao_por_tarefa_e_devolve_um_resultado_por_quadro() -> None:
    modelo = ModeloFalso()
    resultados = DetectorFlorence(modelo).detectar_lote(
        [Image.new("RGB", (200, 100)) for _ in range(3)]
    )
    assert len(resultados) == 3
    assert all(r == resultados[0] and r[0][0].rotulo == "car" for r in resultados)
    assert modelo.chamadas == ["<OD>", "<DENSE_REGION_CAPTION>"]


def test_sem_legendas_so_roda_a_deteccao_e_as_regioes_ficam_vazias() -> None:
    modelo = ModeloFalso()
    objetos, regioes = DetectorFlorence(modelo, legendas=False).detectar(
        Image.new("RGB", (200, 100))
    )
    assert modelo.chamadas == ["<OD>"]
    assert objetos[0].rotulo == "car" and regioes == []


def test_sem_variavel_a_configuracao_e_a_de_antes() -> None:
    padrao = ler_configuracao({})
    assert padrao == Configuracao()
    assert padrao.geracao() == {"max_new_tokens": 1024, "num_beams": 3}
    assert (padrao.lote, padrao.legendas, padrao.pular_repetidos) == (1, True, 0)


def test_variaveis_vazias_valem_o_padrao() -> None:
    assert ler_configuracao({"FLORENCE_FEIXES": " ", "FLORENCE_LEGENDAS": ""}) == (
        Configuracao()
    )


def test_cada_variavel_muda_so_o_seu_campo() -> None:
    c = ler_configuracao(
        {
            "FLORENCE_FEIXES": "1",
            "FLORENCE_LOTE": "8",
            "FLORENCE_MAX_TOKENS": "256",
            "FLORENCE_LEGENDAS": "0",
            "FLORENCE_PULAR_REPETIDOS": "6",
            "FLORENCE_LOG_A_CADA": "10",
        }
    )
    assert c.geracao() == {"max_new_tokens": 256, "num_beams": 1}
    assert (c.lote, c.legendas, c.pular_repetidos, c.log_a_cada) == (8, False, 6, 10)


@pytest.mark.parametrize(
    "ambiente",
    [
        {"FLORENCE_FEIXES": "0"},
        {"FLORENCE_LOTE": "x"},
        {"FLORENCE_LEGENDAS": "talvez"},
        {"FLORENCE_PULAR_REPETIDOS": "-1"},
    ],
)
def test_valor_invalido_e_erro_que_diz_a_variavel(ambiente: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="FLORENCE_"):
        ler_configuracao(ambiente)


def test_a_geracao_configurada_chega_ao_generate_e_o_lote_vai_junto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vistos: dict[str, Any] = {}

    class Ids:
        shape = (2, 77)

    class Processador:
        @staticmethod
        def from_pretrained(pasta: str, **_: Any) -> "Processador":
            return Processador()

        def __call__(self, **kwargs: Any) -> Any:
            vistos["entrada"] = kwargs
            return _Entradas()

        def batch_decode(self, ids: Any, **_: Any) -> list[str]:
            return ["a", "b"]

        def post_process_generation(
            self, texto: str, task: str, image_size: Any
        ) -> dict[str, Any]:
            return {task: {"bboxes": [], "labels": [texto]}}

    class _Entradas(dict):  # type: ignore[type-arg]
        def to(self, *args: Any) -> "_Entradas":
            return self

    class Modelo:
        @staticmethod
        def from_pretrained(pasta: str, **_: Any) -> "Modelo":
            return Modelo()

        def to(self, *_: Any) -> "Modelo":
            return self

        def eval(self) -> "Modelo":
            return self

        def generate(self, **kwargs: Any) -> Ids:
            vistos["geracao"] = kwargs
            return Ids()

    class _Sem:
        def __enter__(self) -> None: ...
        def __exit__(self, *_: object) -> None: ...

    torch: Any = ModuleType("torch")
    torch.float16 = torch.float32 = "t"
    torch.no_grad = _Sem
    monkeypatch.setitem(sys.modules, "torch", torch)
    transformers: Any = ModuleType("transformers")
    transformers.AutoProcessor = Processador
    transformers.Florence2ForConditionalGeneration = Modelo
    monkeypatch.setitem(sys.modules, "transformers", transformers)

    executar = florence._carregar(
        "/m", "cpu", configuracao=Configuracao(feixes=1, max_tokens=300)
    )
    saida = executar([Image.new("RGB", (4, 4)), Image.new("RGB", (4, 4))], "<OD>")

    assert vistos["geracao"]["num_beams"] == 1
    assert vistos["geracao"]["max_new_tokens"] == 300
    assert vistos["entrada"]["text"] == ["<OD>", "<OD>"]
    assert len(vistos["entrada"]["images"]) == 2
    assert [r["labels"] for r in saida] == [["a"], ["b"]]
