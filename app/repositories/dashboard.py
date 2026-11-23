"""Agregações do painel. Todas recebem as condições já montadas (filtros da tela)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import ColumnElement, Date, cast, func, not_, or_, select, true
from sqlalchemy.orm import Session

from app.categories import Category
from app.models import Tender
from app.search_query import SEARCH_REGCONFIG

Conditions = Sequence[ColumnElement[bool]]

_VALUE = func.coalesce(func.sum(Tender.estimated_value), 0)


@dataclass(frozen=True, slots=True)
class Totals:
    tenders: int
    total_value: Decimal
    without_value: int
    open_now: int
    municipalities: int


@dataclass(frozen=True, slots=True)
class Group:
    """Uma linha agregada: quantidade de licitações e soma do valor estimado."""

    key: str
    tenders: int
    total_value: Decimal
    name: str = ""
    state: str = ""


def totals(session: Session, conditions: Conditions, *, open_at: datetime) -> Totals:
    row = session.execute(
        select(
            func.count(),
            _VALUE,
            func.count().filter(Tender.estimated_value.is_(None)),
            func.count().filter(Tender.proposals_close_at > open_at),
            func.count(func.distinct(Tender.municipality_ibge_code)),
        ).where(*conditions)
    ).one()
    return Totals(*row)


def by_municipality(
    session: Session,
    conditions: Conditions,
    *,
    order: Literal["tenders", "value"],
    limit: int,
) -> list[Group]:
    count = func.count()
    sort = (count.desc(), _VALUE.desc()) if order == "tenders" else (_VALUE.desc(), count.desc())
    stmt = (
        select(
            Tender.municipality_ibge_code,
            count,
            _VALUE,
            func.max(Tender.municipality_name),
            func.max(Tender.state),
        )
        .where(*conditions)
        .group_by(Tender.municipality_ibge_code)
        .order_by(*sort, Tender.municipality_ibge_code)
        .limit(limit)
    )
    return [
        Group(key=code, tenders=n, total_value=value, name=name, state=state)
        for code, n, value, name, state in session.execute(stmt)
    ]


def _matches(category: Category) -> ColumnElement[bool]:
    tsquery = func.websearch_to_tsquery(SEARCH_REGCONFIG, category.query)
    return Tender.search_vector.op("@@", is_comparison=True)(tsquery)


def by_category(
    session: Session, conditions: Conditions, categories: Sequence[Category]
) -> tuple[list[Group], Group]:
    """Contagem por categoria (com sobreposição) e o que não casa com nenhuma."""
    matches = [_matches(category) for category in categories]
    none = not_(or_(*matches)) if matches else true()
    columns = []
    for match in [*matches, none]:
        columns += [
            func.count().filter(match),
            func.coalesce(func.sum(Tender.estimated_value).filter(match), 0),
        ]
    row = session.execute(select(*columns).where(*conditions)).one()
    groups = [
        Group(key=category.key, name=category.name, tenders=row[2 * i], total_value=row[2 * i + 1])
        for i, category in enumerate(categories)
    ]
    rest = Group(key="sem_categoria", name="Sem categoria", tenders=row[-2], total_value=row[-1])
    return groups, rest


def by_month(session: Session, conditions: Conditions, *, tz_name: str) -> dict[date, Group]:
    """Agrupa pelo mês da publicação no fuso de exibição (não em UTC)."""
    month = cast(func.date_trunc("month", func.timezone(tz_name, Tender.published_at)), Date)
    stmt = select(month, func.count(), _VALUE).where(*conditions).group_by(month)
    return {
        start: Group(key=start.isoformat(), tenders=n, total_value=value)
        for start, n, value in session.execute(stmt)
    }


def ineffective_category_queries(session: Session, categories: Sequence[Category]) -> list[str]:
    """Categorias cuja busca não tem nenhum termo válido (só palavras vazias)."""
    return [
        category.key
        for category in categories
        if session.scalar(
            select(func.numnode(func.websearch_to_tsquery(SEARCH_REGCONFIG, category.query)))
        )
        == 0
    ]
