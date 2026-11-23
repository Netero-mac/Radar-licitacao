from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.formatting import (
    format_brl,
    format_cnpj,
    format_date,
    format_datetime,
    format_estimated_value,
)

CUIABA = ZoneInfo("America/Cuiaba")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("5260541.6"), "R$ 5.260.541,60"),
        (Decimal("1234.5600"), "R$ 1.234,56"),
        (Decimal("0.005"), "R$ 0,01"),
        (Decimal("999.994"), "R$ 999,99"),
        (Decimal("1000000"), "R$ 1.000.000,00"),
        (Decimal("0"), "R$ 0,00"),
        (Decimal("-12.5"), "-R$ 12,50"),
        (None, "Não informado"),
    ],
)
def test_formata_reais(value: Decimal | None, expected: str) -> None:
    assert format_brl(value) == expected


def test_datas_sao_exibidas_no_fuso_de_cuiaba() -> None:
    utc = datetime(2026, 11, 18, 3, 30, tzinfo=UTC)

    # Cuiabá é UTC-4: 03:30 UTC ainda é dia 17 lá.
    assert format_datetime(utc, CUIABA) == "17/11/2026 23:30"
    assert format_date(utc, CUIABA) == "17/11/2026"
    assert format_datetime(None, CUIABA) == "Não informado"
    assert format_date(None, CUIABA) == "Não informado"


def test_formata_cnpj() -> None:
    assert format_cnpj("03347135000116") == "03.347.135/0001-16"
    assert format_cnpj("123") == "123"


def test_valor_estimado_nos_alertas() -> None:
    assert format_estimated_value(Decimal("0")) == "Sigiloso"
    assert format_estimated_value(Decimal("0.0000")) == "Sigiloso"
    assert format_estimated_value(None) == "Não informado"
    assert format_estimated_value(Decimal("1500.5")) == "R$ 1.500,50"
