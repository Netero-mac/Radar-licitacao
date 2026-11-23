"""Regras do painel: período em meses no fuso de exibição e montagem das respostas."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.categories import CATEGORIES, Category
from app.repositories import dashboard as repository
from app.repositories.tenders import TenderQuery, filter_conditions
from app.schemas.dashboard import (
    CategoryBreakdown,
    CategoryStat,
    DashboardFilters,
    MonthlySeries,
    MonthStat,
    MunicipalityRanking,
    MunicipalityStat,
    Period,
    RankingParams,
    Stat,
    Summary,
)

MONTH_ABBR = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def period(filters: DashboardFilters, tz: ZoneInfo, now: datetime) -> Period:
    today = now.astimezone(tz).date()
    start = _add_months(today.replace(day=1), -(filters.months - 1))
    return Period(start=start, end=today, months=filters.months)


def _conditions(filters: DashboardFilters, current: Period, tz: ZoneInfo) -> list:
    since = datetime.combine(current.start, time.min, tzinfo=tz)
    return filter_conditions(TenderQuery(state=filters.state, published_since=since))


def month_label(month: date) -> str:
    return f"{MONTH_ABBR[month.month - 1]}/{month.year % 100:02d}"


def summary(session: Session, filters: DashboardFilters, tz: ZoneInfo, now: datetime) -> Summary:
    current = period(filters, tz, now)
    totals = repository.totals(session, _conditions(filters, current, tz), open_at=now)
    return Summary(
        period=current,
        tenders=totals.tenders,
        total_value=totals.total_value,
        without_value=totals.without_value,
        secret_value=totals.secret_value,
        open_now=totals.open_now,
        municipalities=totals.municipalities,
    )


def municipalities(
    session: Session,
    filters: DashboardFilters,
    ranking: RankingParams,
    tz: ZoneInfo,
    now: datetime,
) -> MunicipalityRanking:
    current = period(filters, tz, now)
    conditions = _conditions(filters, current, tz)
    groups = repository.by_municipality(
        session, conditions, order=ranking.order, limit=ranking.limit
    )
    return MunicipalityRanking(
        period=current,
        order=ranking.order,
        items=[
            MunicipalityStat(
                key=group.key,
                label=f"{group.name}/{group.state}",
                state=group.state,
                tenders=group.tenders,
                total_value=group.total_value,
            )
            for group in groups
        ],
        total_municipalities=repository.totals(session, conditions, open_at=now).municipalities,
    )


def categories(
    session: Session,
    filters: DashboardFilters,
    tz: ZoneInfo,
    now: datetime,
    definitions: tuple[Category, ...] = CATEGORIES,
) -> CategoryBreakdown:
    current = period(filters, tz, now)
    conditions = _conditions(filters, current, tz)
    groups, rest = repository.by_category(session, conditions, definitions)
    keywords = {category.key: list(category.keywords) for category in definitions}
    items = [
        CategoryStat(
            key=group.key,
            label=group.name,
            tenders=group.tenders,
            total_value=group.total_value,
            keywords=keywords[group.key],
        )
        for group in groups
    ]
    # Ordem por quantidade; o empate mantém a ordem da definição (estável).
    items.sort(key=lambda item: item.tenders, reverse=True)
    return CategoryBreakdown(
        period=current,
        items=items,
        uncategorized=Stat(
            key=rest.key, label=rest.name, tenders=rest.tenders, total_value=rest.total_value
        ),
        total_tenders=repository.totals(session, conditions, open_at=now).tenders,
    )


def monthly(
    session: Session, filters: DashboardFilters, tz: ZoneInfo, now: datetime
) -> MonthlySeries:
    current = period(filters, tz, now)
    groups = repository.by_month(session, _conditions(filters, current, tz), tz_name=tz.key)
    items = []
    for offset in range(current.months):
        month = _add_months(current.start, offset)
        group = groups.get(month)
        items.append(
            MonthStat(
                key=month.isoformat(),
                label=month_label(month),
                month=month,
                partial=offset == current.months - 1,
                tenders=group.tenders if group else 0,
                total_value=group.total_value if group else 0,
            )
        )
    return MonthlySeries(period=current, items=items)
