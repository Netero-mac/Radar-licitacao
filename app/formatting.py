"""Formatação para exibição em português do Brasil (sem depender do locale do sistema)."""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

NOT_INFORMED = "Não informado"


def format_brl(value: Decimal | None) -> str:
    """Ex.: Decimal("5260541.6") -> R$ 5.260.541,60."""
    if value is None:
        return NOT_INFORMED
    cents = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer, _, fraction = f"{abs(cents):f}".partition(".")
    grouped = f"{int(integer):,}".replace(",", ".")
    sign = "-" if cents < 0 else ""
    return f"{sign}R$ {grouped},{fraction or '00'}"


def format_datetime(value: datetime | None, tz: ZoneInfo) -> str:
    """Instante UTC -> "22/11/2026 21:30" no fuso de exibição."""
    if value is None:
        return NOT_INFORMED
    return value.astimezone(tz).strftime("%d/%m/%Y %H:%M")


def format_date(value: datetime | None, tz: ZoneInfo) -> str:
    if value is None:
        return NOT_INFORMED
    return value.astimezone(tz).strftime("%d/%m/%Y")


def format_cnpj(value: str) -> str:
    """Ex.: 03347135000116 -> 03.347.135/0001-16 (valores fora do padrão saem como vieram)."""
    if len(value) != 14 or not value.isdigit():
        return value
    return f"{value[:2]}.{value[2:5]}.{value[5:8]}/{value[8:12]}-{value[12:]}"
