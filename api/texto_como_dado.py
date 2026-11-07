"""Texto de quem usa é dado, não instrução: tamanho, caracteres de controle e ids (#461, #474).

Todo campo de texto dos pedidos usa `Linha` (uma linha só) ou `Texto` (aceita quebra de linha e
tabulação), sempre com `max_length`; os dois recusam caractere de controle com 422. Um id que
vira caminho de documento ou de objeto passa por `id_seguro` antes de chegar ao Firestore ou ao
Storage (`conferir_ids_e_consultas` confere os parâmetros de toda rota).
"""

import re
from typing import Any

from fastapi import HTTPException, Query, Request
from pydantic import AfterValidator, StringConstraints

# Controle C0 e C1 (inclui NUL e DEL). O `Texto` deixa passar tabulação, `\n` e `\r`.
_CONTROLE = r"\x00-\x1f\x7f-\x9f"
_CONTROLE_SALVO_QUEBRA = r"\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f"
_CONTROLE_DA_LINHA = re.compile(f"[{_CONTROLE}]")
_CONTROLE_DO_TEXTO = re.compile(f"[{_CONTROLE_SALVO_QUEBRA}]")

PADRAO_DA_LINHA = f"^[^{_CONTROLE}]*$"
PADRAO_DO_TEXTO = f"^[^{_CONTROLE_SALVO_QUEBRA}]*$"

TAMANHO_MAXIMO_DO_ID = 200
# Teto de qualquer parâmetro de consulta; cada um tem o seu, bem menor (a lista de ids do
# andamento é a maior).
TAMANHO_MAXIMO_DO_PARAMETRO = 10_000
# Parâmetros de consulta que a rota usa como id de documento, além dos `*_id`: o cursor das
# listagens paginadas (o id do último documento, ou uma posição) e a lista do andamento.
_CONSULTAS_COM_ID = {"cursor"}
_CONSULTAS_COM_IDS = {"ids"}


def Linha(
    max_length: int, *, min_length: int = 0, strip: bool = False
) -> StringConstraints:
    """Texto de uma linha: `Annotated[str, Linha(255)]`, com tamanho limitado e sem caractere de
    controle."""
    return StringConstraints(
        min_length=min_length,
        max_length=max_length,
        pattern=PADRAO_DA_LINHA,
        strip_whitespace=strip,
    )


def Texto(
    max_length: int, *, min_length: int = 0, strip: bool = False
) -> StringConstraints:
    """Texto livre: aceita quebra de linha e tabulação, mas não outro caractere de controle."""
    return StringConstraints(
        min_length=min_length,
        max_length=max_length,
        pattern=PADRAO_DO_TEXTO,
        strip_whitespace=strip,
    )


def LinhaDaConsulta(max_length: int, *, min_length: int = 0, **extras: Any) -> Any:
    """`Query` de uma linha só: `Annotated[str | None, LinhaDaConsulta(100)] = None`."""
    return Query(
        min_length=min_length, max_length=max_length, pattern=PADRAO_DA_LINHA, **extras
    )


def tem_controle(valor: str, *, permite_quebra: bool = False) -> bool:
    """Se o texto traz caractere de controle (a quebra de linha só vale com `permite_quebra`)."""
    achado = _CONTROLE_DO_TEXTO if permite_quebra else _CONTROLE_DA_LINHA
    return achado.search(valor) is not None


def id_seguro(valor: str) -> bool:
    """Se o texto pode virar o último trecho de um caminho de documento ou de objeto: não vazio,
    sem `/`, `\\`, `..` nem caractere de controle, e de tamanho limitado."""
    return (
        0 < len(valor) <= TAMANHO_MAXIMO_DO_ID
        and "/" not in valor
        and "\\" not in valor
        and ".." not in valor
        and valor != "."
        and not tem_controle(valor)
    )


def conferir_ids_e_consultas(request: Request) -> None:
    """Dependência do app inteiro: todo parâmetro de caminho é um id seguro, e todo parâmetro de
    consulta é curto e sem caractere de controle. Recusa com 422 antes de a rota rodar."""
    for nome, valor in request.path_params.items():
        if not isinstance(valor, str) or not id_seguro(valor):
            raise HTTPException(422, f"parâmetro de caminho inválido: {nome}")
    for nome, valor in request.query_params.multi_items():
        if len(valor) > TAMANHO_MAXIMO_DO_PARAMETRO or tem_controle(valor):
            raise HTTPException(422, f"parâmetro de consulta inválido: {nome}")
        # `?destino_id=`, `?cursor=` e afins: id que a rota usa como o de um documento.
        if (nome.endswith("_id") or nome in _CONSULTAS_COM_ID) and not id_seguro(valor):
            raise HTTPException(422, f"parâmetro de consulta inválido: {nome}")
        if nome in _CONSULTAS_COM_IDS and not all(
            id_seguro(i) for i in (p.strip() for p in valor.split(",")) if i
        ):
            raise HTTPException(422, f"parâmetro de consulta inválido: {nome}")


def id_conferido(valor: str) -> str:
    """O próprio `valor`, se é um id seguro; senão `ValueError`. Os adaptadores do Firestore e
    do Storage a chamam de novo (defesa em profundidade: a API já recusou com 422)."""
    if not id_seguro(valor):
        raise ValueError("id inválido: sem barra, '..' nem caractere de controle")
    return valor


# Para o id que vem no corpo e vira documento ou objeto: `Annotated[str, Linha(64, min_length=1), ID_SEGURO]`.
ID_SEGURO = AfterValidator(id_conferido)
