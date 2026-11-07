"""O período padrão dos relatórios (#462): os últimos 7 dias, de hoje − 6 até hoje, no dia de
São Paulo. Vale quando o pedido não traz `desde` nem `ate`; `desde=&ate=` (vazios) pede o
histórico inteiro, e qualquer um dos dois preenchido vale como veio.

A web tem a mesma conta em `web/src/periodoPadrao.ts`; um teste compara o número dos dois."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Annotated, NamedTuple

from fastapi import HTTPException, Query

from api.qualidade_do_painel import SAO_PAULO

DIAS_DO_PERIODO_PADRAO = 7


class Periodo(NamedTuple):
    desde: date | None
    ate: date | None


def agora_em_sao_paulo() -> datetime:
    return datetime.now(SAO_PAULO)


def periodo_padrao(agora: datetime) -> Periodo:
    hoje = agora.astimezone(SAO_PAULO).date()
    return Periodo(hoje - timedelta(days=DIAS_DO_PERIODO_PADRAO - 1), hoje)


def _data(nome: str, valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError as e:
        raise HTTPException(422, f"`{nome}` não é uma data (AAAA-MM-DD)") from e


def dependencia_do_periodo(
    relogio: Callable[[], datetime] = agora_em_sao_paulo,
) -> Callable[..., Periodo]:
    """A dependência das rotas com `desde` e `ate`, com o relógio que o teste troca."""

    def periodo(
        desde: Annotated[
            str | None,
            Query(
                description="Dia (AAAA-MM-DD); sem `desde` nem `ate`, os últimos 7 dias"
            ),
        ] = None,
        ate: Annotated[str | None, Query(description="Dia (AAAA-MM-DD)")] = None,
    ) -> Periodo:
        if desde is None and ate is None:
            return periodo_padrao(relogio())
        return Periodo(_data("desde", desde), _data("ate", ate))

    return periodo
