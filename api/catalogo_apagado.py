"""A leitura da Decupagem sem o que saiu do catálogo (lixeira ou purga) (#151).

Só a leitura muda: a saída do modelo e as correções ficam como estão (ADR 0010).
"""

from collections.abc import Callable
from typing import Any

from api.catalogo import PessoaDoCatalogo
from api.comparador import normalizar

# O que sustenta um nome "só pelo rosto": sem GC nem fala.
FONTES_DO_ROSTO = frozenset({"rosto", "referencia"})
NAO_IDENTIFICADO = "não identificado"
CATALOGO_ID = "catalogo_id"


def ids_do_catalogo(entregue: dict[str, Any], campo: str) -> list[str]:
    """Os `catalogo_id` distintos de `pessoas` ou `comerciais`, na ordem em que aparecem."""
    ids = (
        item.get(CATALOGO_ID) if isinstance(item, dict) else None
        for item in entregue.get(campo) or []
    )
    return list(dict.fromkeys(i for i in ids if isinstance(i, str)))


def lido_em_lote[T](
    ids: list[str],
    em_lote: Callable[[list[str]], dict[str, T]],
    obter: Callable[[str], T | None],
) -> Callable[[str], T | None]:
    """Um `obter` que serve os `ids` de uma leitura em lote só; o que não veio nela (o
    destino de uma fusão, por exemplo) cai em `obter`."""
    lidos = em_lote(ids)
    return lambda id: lidos[id] if id in lidos else obter(id)


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
    fusão em cadeia (A em B, depois B em C) leva ao último destino. Também troca o nome
    que a pessoa teve antes de uma renomeação em todos os vídeos (#263) pelo atual; um
    nome que o editor corrigiu no vídeo para outro fica como está."""
    for pessoa in entregue.get("pessoas") or []:
        id = pessoa.get("catalogo_id") if isinstance(pessoa, dict) else None
        if id is None:
            continue
        destino = _destino_final(id, obter)
        if destino is not None:
            pessoa.update(nome=destino.nome, catalogo_id=destino.id)
            continue
        atual = obter(id)
        if atual is not None and atual.renomeacao is not None:
            antigos = {normalizar(n) for n in atual.renomeacao.nomes_anteriores}
            if normalizar(str(pessoa.get("nome"))) in antigos:
                pessoa["nome"] = atual.nome
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
