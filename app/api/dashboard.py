"""API JSON do painel (alimenta os gráficos de /painel; documentada em /docs)."""

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.templating import display_timezone
from app.db import get_session
from app.schemas.dashboard import (
    CategoryBreakdown,
    DashboardFilters,
    MonthlySeries,
    MunicipalityRanking,
    RankingParams,
    Summary,
)
from app.services import dashboard as service

router = APIRouter(prefix="/api/dashboard", tags=["painel"])

SessionDep = Annotated[Session, Depends(get_session)]
TimezoneDep = Annotated[ZoneInfo, Depends(display_timezone)]
FiltersDep = Annotated[DashboardFilters, Query()]

_MONEY = (
    "Valores como texto decimal; licitações sem valor estimado contam na quantidade, não na soma."
)


@router.get("/summary", response_model=Summary, summary="Totais do período")
def get_summary(filters: FiltersDep, session: SessionDep, tz: TimezoneDep) -> Summary:
    return service.summary(session, filters, tz, datetime.now(UTC))


@router.get(
    "/municipalities",
    response_model=MunicipalityRanking,
    summary="Ranking de municípios por quantidade ou valor",
    description=_MONEY,
)
def get_municipalities(
    filters: FiltersDep,
    ranking: Annotated[RankingParams, Query()],
    session: SessionDep,
    tz: TimezoneDep,
) -> MunicipalityRanking:
    return service.municipalities(session, filters, ranking, tz, datetime.now(UTC))


@router.get(
    "/categories",
    response_model=CategoryBreakdown,
    summary="Licitações por categoria (agrupamento por palavras-chave no objeto)",
    description=_MONEY + " As categorias se sobrepõem.",
)
def get_categories(filters: FiltersDep, session: SessionDep, tz: TimezoneDep) -> CategoryBreakdown:
    return service.categories(session, filters, tz, datetime.now(UTC))


@router.get(
    "/monthly",
    response_model=MonthlySeries,
    summary="Evolução mensal (mês da publicação, no fuso de exibição)",
    description=_MONEY,
)
def get_monthly(filters: FiltersDep, session: SessionDep, tz: TimezoneDep) -> MonthlySeries:
    return service.monthly(session, filters, tz, datetime.now(UTC))
