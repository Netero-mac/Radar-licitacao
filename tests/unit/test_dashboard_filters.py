from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.categories import CATEGORIES
from app.formatting import format_brl_compact, format_day, format_number
from app.schemas.dashboard import DashboardFilters
from app.services.dashboard import month_label, period

BRASILIA = ZoneInfo("America/Sao_Paulo")


def test_filtros_padrao_e_invalidos() -> None:
    assert DashboardFilters.from_query_lenient({}) == (DashboardFilters(), [])

    filters, errors = DashboardFilters.from_query_lenient({"months": "5", "state": "mt"})

    assert (filters.months, filters.state) == (12, "MT")
    assert errors == ["Período: escolha 3, 6, 12 ou 24 meses"]
    assert DashboardFilters(months=3, state="MT").query_params() == {"months": "3", "state": "MT"}


@pytest.mark.parametrize(
    ("now", "months", "start", "end"),
    [
        (datetime(2026, 11, 22, 15, tzinfo=UTC), 12, date(2025, 12, 1), date(2026, 11, 22)),
        (datetime(2026, 11, 22, 15, tzinfo=UTC), 3, date(2026, 9, 1), date(2026, 11, 22)),
        # 1º de dezembro 01:00 UTC ainda é 30 de novembro em Brasília
        (datetime(2026, 12, 1, 1, tzinfo=UTC), 3, date(2026, 9, 1), date(2026, 11, 30)),
        (datetime(2026, 2, 10, 12, tzinfo=UTC), 24, date(2024, 3, 1), date(2026, 2, 10)),
    ],
)
def test_periodo_em_meses_no_fuso_de_exibicao(
    now: datetime, months: int, start: date, end: date
) -> None:
    current = period(DashboardFilters(months=months), BRASILIA, now)

    assert (current.start, current.end, current.months) == (start, end, months)


def test_formatos() -> None:
    assert month_label(date(2026, 3, 1)) == "mar/26"
    assert format_number(12345) == "12.345"
    assert format_day(date(2026, 11, 1)) == "01/11/2026"
    assert format_brl_compact(Decimal("4912345678.9")) == "R$ 4,9 bi"
    assert format_brl_compact(Decimal("12000000")) == "R$ 12 mi"
    assert format_brl_compact(Decimal("350400")) == "R$ 350,4 mil"
    assert format_brl_compact(Decimal("999.5")) == "R$ 999,50"


def test_categorias_tem_chaves_unicas_e_termos() -> None:
    assert len({category.key for category in CATEGORIES}) == len(CATEGORIES)
    assert all(category.keywords for category in CATEGORIES)
    assert CATEGORIES[0].query.startswith("computador OR notebook")
