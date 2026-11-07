"""A contagem de itens por tipo de correção de cada decupagem (#455).

A taxa de correção divide as correções pelos itens da decupagem, e baixar a decupagem (cerca
de 0,5 MB) a cada abertura do painel não escala. A contagem é feita uma vez, quando a decupagem
é gravada (a análise, o reprocessamento, a identificação, os quadros e o inventário gravam),
e fica num objeto pequeno ao lado dela: `<job>/itens_por_tipo.json`.
"""

import json
from dataclasses import dataclass
from typing import Any, get_args

from api.correcoes import CORRIGIVEIS, TIPOS, TipoDoItem, _itens, versao_do_modelo


def objeto_dos_itens(job_id: str) -> str:
    return f"{job_id}/itens_por_tipo.json"


def itens_do_tipo(modelo: dict[str, Any], tipo: str) -> int:
    """Quantos itens do tipo do item que a correção do `tipo` corrige."""
    do_item = TIPOS[tipo].tipo_do_item
    tipos = get_args(TipoDoItem) if do_item is None else (do_item,)
    return sum(len(_itens(modelo, t)) for t in tipos)


@dataclass(frozen=True)
class ItensDaDecupagem:
    """O que a taxa lê da decupagem: a versão do JSON (a que a correção ancora), a versão do
    pipeline e os itens de cada tipo de correção."""

    versao_do_modelo: str
    versao_pipeline: str | None
    itens: dict[str, int]

    def em_json(self) -> str:
        return json.dumps(
            {
                "versao_do_modelo": self.versao_do_modelo,
                "versao_pipeline": self.versao_pipeline,
                "itens": self.itens,
            }
        )

    @classmethod
    def do_json(cls, texto: str | bytes) -> "ItensDaDecupagem":
        dados = json.loads(texto)
        return cls(
            versao_do_modelo=dados["versao_do_modelo"],
            versao_pipeline=dados["versao_pipeline"],
            itens={tipo: int(n) for tipo, n in dados["itens"].items()},
        )


def contar_itens(conteudo: bytes) -> ItensDaDecupagem:
    """Levanta `ValueError` ou `TypeError` se o conteúdo não é uma decupagem legível."""
    modelo = json.loads(conteudo)
    if not isinstance(modelo, dict):
        raise TypeError("a decupagem não é um objeto")
    versao_pipeline = modelo.get("versao_pipeline")
    return ItensDaDecupagem(
        versao_do_modelo=versao_do_modelo(conteudo),
        versao_pipeline=versao_pipeline if isinstance(versao_pipeline, str) else None,
        itens={tipo: itens_do_tipo(modelo, tipo) for tipo in CORRIGIVEIS},
    )
