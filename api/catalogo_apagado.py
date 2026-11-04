"""A leitura da Decupagem sem o que saiu do catálogo (lixeira ou purga) (#151).

Só a leitura muda: a saída do modelo e as correções ficam como estão (ADR 0010).
"""

from collections.abc import Callable
from typing import Any

from api.catalogo import PessoaDoCatalogo

# O que sustenta um nome "só pelo rosto": sem GC nem fala.
FONTES_DO_ROSTO = frozenset({"rosto", "referencia"})
NAO_IDENTIFICADO = "não identificado"


def so_o_rosto(fontes: list[str]) -> bool:
    return bool(fontes) and set(fontes) <= FONTES_DO_ROSTO


def sem_catalogo_apagado(
    entregue: dict[str, Any],
    pessoa_viva: Callable[[str], bool],
    marca_viva: Callable[[str], bool],
) -> dict[str, Any]:
    """A leitura da Decupagem com o que saiu do catálogo (lixeira ou purga): a pessoa
    cujo nome só o rosto sustentava volta a "não identificado"; as confirmadas por GC ou
    fala mantêm o nome; os dois perdem o `catalogo_id`, e a marca mantém o texto."""
    for pessoa in entregue.get("pessoas") or []:
        id = pessoa.get("catalogo_id") if isinstance(pessoa, dict) else None
        if id is None or pessoa_viva(id):
            continue
        pessoa.pop("catalogo_id")
        if so_o_rosto(pessoa.get("fontes_do_nome") or []):
            pessoa.update(
                nome=NAO_IDENTIFICADO,
                origem="modelo",
                estado_do_nome=None,
                fontes_do_nome=[],
            )
    for comercial in entregue.get("comerciais") or []:
        id = comercial.get("catalogo_id") if isinstance(comercial, dict) else None
        if id is not None and not marca_viva(id):
            comercial.pop("catalogo_id")
    return entregue


def com_pessoas_fundidas(
    entregue: dict[str, Any],
    obter: Callable[[str], PessoaDoCatalogo | None],
) -> dict[str, Any]:
    """A leitura da Decupagem com o destino no lugar da pessoa fundida (#209): o
    `catalogo_id` e o nome passam a ser os do destino; o que está gravado não muda. A
    fusão em cadeia (A em B, depois B em C) leva ao último destino."""
    for pessoa in entregue.get("pessoas") or []:
        id = pessoa.get("catalogo_id") if isinstance(pessoa, dict) else None
        destino = _destino_final(id, obter) if id is not None else None
        if destino is not None:
            pessoa.update(nome=destino.nome, catalogo_id=destino.id)
    return entregue


def _destino_final(
    id: str, obter: Callable[[str], PessoaDoCatalogo | None]
) -> PessoaDoCatalogo | None:
    """O destino em que a pessoa acabou fundida, ou `None` se ela não foi fundida."""
    achada = obter(id)
    vistos = {id}
    while achada is not None and achada.fundida is not None:
        proximo = achada.fundida.destino_id
        if proximo in vistos:
            return None
        vistos.add(proximo)
        achada = obter(proximo)
    return achada if achada is not None and len(vistos) > 1 else None
