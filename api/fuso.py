"""O "dia" e o "agora" de São Paulo, num lugar só (#636). Só biblioteca padrão."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def agora_em_sao_paulo() -> datetime:
    return datetime.now(SAO_PAULO)


def periodo_em_utc(
    desde: date | None, ate: date | None
) -> tuple[datetime | None, datetime | None]:
    """`[00:00 de desde, 00:00 do dia seguinte a ate)` em UTC; `None` em cada ponta ausente."""
    return (
        datetime.combine(desde, time.min, SAO_PAULO).astimezone(UTC) if desde else None,
        datetime.combine(ate + timedelta(days=1), time.min, SAO_PAULO).astimezone(UTC)
        if ate
        else None,
    )
