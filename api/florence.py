"""Florence-2: formato guardado dos objetos por quadro e adaptador do modelo.

O adaptador é o único lugar que importa `torch` e `transformers`; o grupo de
dependências `objetos` não entra no `make verificar`, e os testes passam um modelo falso.
O modelo é a conversão oficial para o transformers (sem `trust_remote_code`), com os
pesos na pasta da imagem, sem internet. As caixas são normalizadas de 0 a 1, como as do OCR.
"""

import logging
from collections.abc import Callable
from typing import Any

from PIL import Image
from pydantic import BaseModel, ConfigDict

from api.dispositivo import Dispositivo, exigir_gpu, ler_dispositivo
from api.leitura_da_tela import Caixa

log = logging.getLogger(__name__)

VERSAO_DO_FORMATO = 1
MODELO = "florence-community/Florence-2-large"
REVISAO = "4271c66b88cdbc05735372ec13b2360108de5317"
NOME_DO_MODELO = f"{MODELO}@{REVISAO}"

DETECCAO = "<OD>"
REGIOES = "<DENSE_REGION_CAPTION>"
GERACAO = {"max_new_tokens": 1024, "num_beams": 3}


class ObjetoDetectado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rotulo: str
    caixa: Caixa


class RegiaoLegendada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legenda: str
    caixa: Caixa


class QuadroDetectado(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plano: int
    caminho: str
    largura: int
    altura: int
    objetos: list[ObjetoDetectado]
    regioes: list[RegiaoLegendada]


class ObjetosDaDecupagem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    versao: int = VERSAO_DO_FORMATO
    modelo: str
    quadros: list[QuadroDetectado]


def _gpus() -> int:
    import torch

    return int(torch.cuda.device_count())


def _carregar(
    pasta_do_modelo: str,
    dispositivo: Dispositivo = "cpu",
    gpus: Callable[[], int] | None = None,
) -> Callable[[Image.Image, str], dict[str, Any]]:
    """Devolve a função `(imagem, tarefa) -> {'bboxes': [...], 'labels': [...]}` em pixels."""
    import torch
    from transformers import AutoProcessor, Florence2ForConditionalGeneration

    if dispositivo == "gpu":
        exigir_gpu((gpus or _gpus)(), "o PyTorch")
    log.info("Inventário de objetos em %s", dispositivo)
    destino = "cuda" if dispositivo == "gpu" else "cpu"
    tipo = torch.float16 if dispositivo == "gpu" else torch.float32
    processador = AutoProcessor.from_pretrained(pasta_do_modelo, local_files_only=True)
    modelo = (
        Florence2ForConditionalGeneration.from_pretrained(
            pasta_do_modelo, local_files_only=True, torch_dtype=tipo
        )
        .to(destino)
        .eval()
    )

    def executar(imagem: Image.Image, tarefa: str) -> dict[str, Any]:
        entradas = processador(text=tarefa, images=imagem, return_tensors="pt").to(
            destino, tipo
        )
        with torch.no_grad():
            ids = modelo.generate(**entradas, **GERACAO)
        texto = processador.batch_decode(ids, skip_special_tokens=False)[0]
        resultado: dict[str, Any] = processador.post_process_generation(
            texto, task=tarefa, image_size=imagem.size
        )[tarefa]
        return resultado

    return executar


def _caixa(pixels: Any, largura: int, altura: int) -> Caixa:
    x0, y0, x1, y1 = (float(v) for v in pixels)
    return Caixa(
        x=x0 / largura,
        y=y0 / altura,
        largura=(x1 - x0) / largura,
        altura=(y1 - y0) / altura,
    )


class DetectorFlorence:
    def __init__(self, modelo: Callable[[Image.Image, str], dict[str, Any]]) -> None:
        self._modelo = modelo

    @classmethod
    def da_pasta(
        cls,
        pasta_do_modelo: str,
        dispositivo: Dispositivo | None = None,
        carregar: Callable[..., Any] = _carregar,
    ) -> "DetectorFlorence":
        """`dispositivo` vem da variável `DISPOSITIVO` (cpu, por padrão) se não for dado."""
        return cls(carregar(pasta_do_modelo, dispositivo or ler_dispositivo()))

    def detectar(
        self, imagem: Image.Image
    ) -> tuple[list[ObjetoDetectado], list[RegiaoLegendada]]:
        largura, altura = imagem.size
        achados = self._modelo(imagem, DETECCAO)
        regioes = self._modelo(imagem, REGIOES)
        objetos = [
            ObjetoDetectado(rotulo=r.strip(), caixa=_caixa(c, largura, altura))
            for c, r in zip(achados["bboxes"], achados["labels"], strict=True)
            if r.strip()
        ]
        legendas = [
            RegiaoLegendada(legenda=r.strip(), caixa=_caixa(c, largura, altura))
            for c, r in zip(regioes["bboxes"], regioes["labels"], strict=True)
            if r.strip()
        ]
        return objetos, legendas
