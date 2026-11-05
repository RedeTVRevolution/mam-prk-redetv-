"""Florence-2: formato guardado dos objetos por quadro e adaptador do modelo.

O adaptador é o único lugar que importa `torch` e `transformers`; o grupo de
dependências `objetos` não entra no `make verificar`, e os testes passam um modelo falso.
O modelo é a conversão oficial para o transformers (sem `trust_remote_code`), com os
pesos na pasta da imagem, sem internet. As caixas são normalizadas de 0 a 1, como as do OCR.
"""

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Configuracao:
    """As variações do Florence-2 medidas no #329. O padrão é o comportamento de antes."""

    feixes: int = 3
    lote: int = 1  # quadros por `generate`
    max_tokens: int = 1024
    legendas: bool = True  # a segunda geração (`<DENSE_REGION_CAPTION>`) de cada quadro
    pular_repetidos: int = 0  # distância de hash entre quadros do plano; 0 = não pula
    log_a_cada: int = 25  # quadros entre duas linhas de progresso

    def geracao(self) -> dict[str, int]:
        return {"max_new_tokens": self.max_tokens, "num_beams": self.feixes}


# A geração padrão: entra na versão do pipeline (`api/versao_pipeline.py`).
GERACAO = Configuracao().geracao()


def _inteiro(ambiente: Mapping[str, str], nome: str, padrao: int, minimo: int) -> int:
    texto = ambiente.get(nome, "").strip()
    if not texto:
        return padrao
    try:
        valor = int(texto)
    except ValueError:
        raise ValueError(f"{nome}={texto!r} não é um número inteiro.") from None
    if valor < minimo:
        raise ValueError(f"{nome}={valor} é menor que {minimo}.")
    return valor


def ler_configuracao(ambiente: Mapping[str, str] | None = None) -> Configuracao:
    """Lê `FLORENCE_FEIXES`, `FLORENCE_LOTE`, `FLORENCE_MAX_TOKENS`, `FLORENCE_LEGENDAS`
    (`0` desliga), `FLORENCE_PULAR_REPETIDOS` (distância máxima de hash; `0` desliga) e
    `FLORENCE_LOG_A_CADA`. Variável ausente ou vazia vale o padrão."""
    e = os.environ if ambiente is None else ambiente
    padrao = Configuracao()
    legendas = e.get("FLORENCE_LEGENDAS", "").strip()
    if legendas not in ("", "0", "1"):
        raise ValueError(f"FLORENCE_LEGENDAS={legendas!r}: use 0 ou 1.")
    return Configuracao(
        feixes=_inteiro(e, "FLORENCE_FEIXES", padrao.feixes, 1),
        lote=_inteiro(e, "FLORENCE_LOTE", padrao.lote, 1),
        max_tokens=_inteiro(e, "FLORENCE_MAX_TOKENS", padrao.max_tokens, 1),
        legendas=legendas != "0",
        pular_repetidos=_inteiro(
            e, "FLORENCE_PULAR_REPETIDOS", padrao.pular_repetidos, 0
        ),
        log_a_cada=_inteiro(e, "FLORENCE_LOG_A_CADA", padrao.log_a_cada, 1),
    )


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
    # Só quando o resultado vai para um destino alternativo (a medição do #329).
    segundos: float | None = None


def _gpus() -> int:
    import torch

    return int(torch.cuda.device_count())


def _carregar(
    pasta_do_modelo: str,
    dispositivo: Dispositivo = "cpu",
    gpus: Callable[[], int] | None = None,
    configuracao: Configuracao | None = None,
) -> Callable[[list[Image.Image], str], list[dict[str, Any]]]:
    """Devolve a função `(imagens, tarefa) -> [{'bboxes': [...], 'labels': [...]}, ...]`,
    uma resposta por imagem, em pixels. As imagens do lote vão num `generate` só."""
    import torch
    from transformers import AutoProcessor, Florence2ForConditionalGeneration

    if dispositivo == "gpu":
        exigir_gpu((gpus or _gpus)(), "o PyTorch")
    geracao = (configuracao or Configuracao()).geracao()
    log.info("Inventário de objetos em %s, geração %s", dispositivo, geracao)
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

    maior = 0

    def executar(imagens: list[Image.Image], tarefa: str) -> list[dict[str, Any]]:
        entradas = processador(
            text=[tarefa] * len(imagens),
            images=imagens,
            return_tensors="pt",
            padding=True,
        ).to(destino, tipo)
        with torch.no_grad():
            ids = modelo.generate(**entradas, **geracao)
        nonlocal maior
        if ids.shape[-1] > maior:  # uma linha só quando cresce: guia o teto de tokens
            maior = ids.shape[-1]
            log.info("Maior resposta até aqui: %d tokens (%s)", maior, tarefa)
        textos = processador.batch_decode(ids, skip_special_tokens=False)
        return [
            processador.post_process_generation(
                texto, task=tarefa, image_size=imagem.size
            )[tarefa]
            for texto, imagem in zip(textos, imagens, strict=True)
        ]

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
    def __init__(
        self,
        modelo: Callable[[list[Image.Image], str], list[dict[str, Any]]],
        legendas: bool = True,
    ) -> None:
        self._modelo = modelo
        self._legendas = legendas

    @classmethod
    def da_pasta(
        cls,
        pasta_do_modelo: str,
        dispositivo: Dispositivo | None = None,
        carregar: Callable[..., Any] = _carregar,
        configuracao: Configuracao | None = None,
    ) -> "DetectorFlorence":
        """`dispositivo` vem da variável `DISPOSITIVO` (cpu, por padrão) se não for dado."""
        configuracao = configuracao or Configuracao()
        modelo = carregar(
            pasta_do_modelo,
            dispositivo or ler_dispositivo(),
            configuracao=configuracao,
        )
        return cls(modelo, configuracao.legendas)

    def detectar(
        self, imagem: Image.Image
    ) -> tuple[list[ObjetoDetectado], list[RegiaoLegendada]]:
        return self.detectar_lote([imagem])[0]

    def detectar_lote(
        self, imagens: list[Image.Image]
    ) -> list[tuple[list[ObjetoDetectado], list[RegiaoLegendada]]]:
        achados = self._modelo(imagens, DETECCAO)
        legendadas = self._modelo(imagens, REGIOES) if self._legendas else None
        resultado = []
        for i, imagem in enumerate(imagens):
            largura, altura = imagem.size
            objetos = [
                ObjetoDetectado(rotulo=r.strip(), caixa=_caixa(c, largura, altura))
                for c, r in zip(achados[i]["bboxes"], achados[i]["labels"], strict=True)
                if r.strip()
            ]
            regioes = (
                [
                    RegiaoLegendada(legenda=r.strip(), caixa=_caixa(c, largura, altura))
                    for c, r in zip(
                        legendadas[i]["bboxes"], legendadas[i]["labels"], strict=True
                    )
                    if r.strip()
                ]
                if legendadas
                else []
            )
            resultado.append((objetos, regioes))
        return resultado
