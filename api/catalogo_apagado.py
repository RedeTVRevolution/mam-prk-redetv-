"""A leitura da Decupagem sem o que saiu do catálogo (lixeira ou purga) (#151).

Só a leitura muda: a saída do modelo e as correções ficam como estão (ADR 0010).
"""

from collections.abc import Callable
from typing import Any

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
    """Um `obter` que serve os `ids` de uma leitura em lote só: o id do lote que não veio
    nela (apagado) é `None`, e o que estava fora do lote (o destino de uma fusão, por
    exemplo) cai em `obter` uma vez; as respostas ficam guardadas."""
    lidos: dict[str, T | None] = dict.fromkeys(ids)
    lidos.update(em_lote(ids))

    def lido(id: str) -> T | None:
        if id not in lidos:
            lidos[id] = obter(id)
        return lidos[id]

    return lido


def so_o_rosto(fontes: list[str]) -> bool:
    return bool(fontes) and set(fontes) <= FONTES_DO_ROSTO


def sem_catalogo_apagado(
    entregue: dict[str, Any],
    pessoa_viva: Callable[[dict[str, Any]], bool],
    marca_viva: Callable[[str], bool],
) -> dict[str, Any]:
    """A leitura da Decupagem com o que saiu do catálogo (lixeira ou purga): a pessoa
    cujo nome só o rosto sustentava volta a "não identificado"; as confirmadas por GC ou
    fala mantêm o nome; os dois perdem o `catalogo_id`, e a marca mantém o texto."""
    for pessoa in entregue.get("pessoas") or []:
        tem_vinculo = isinstance(pessoa, dict) and pessoa.get(CATALOGO_ID) is not None
        if not tem_vinculo or pessoa_viva(pessoa):
            continue
        pessoa.pop(CATALOGO_ID)
        if so_o_rosto(pessoa.get("fontes_do_nome") or []):
            pessoa.update(
                nome=NAO_IDENTIFICADO,
                origem="modelo",
                estado_do_nome=None,
                fontes_do_nome=[],
            )
    for comercial in entregue.get("comerciais") or []:
        id = comercial.get(CATALOGO_ID) if isinstance(comercial, dict) else None
        if id is not None and not marca_viva(id):
            comercial.pop(CATALOGO_ID)
    return entregue
