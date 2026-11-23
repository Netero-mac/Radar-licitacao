"""Regras da consulta de licitações: filtros da tela/API -> critérios do banco."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Tender
from app.repositories import tenders as repository
from app.repositories.tenders import TenderQuery
from app.schemas.tenders import AgencyOut, TenderDetail, TenderFilters, TenderPage, TenderSummary


def _start_of_day(day: date, tz: ZoneInfo) -> datetime:
    """Meia-noite do dia no fuso de exibição, em UTC (o banco guarda tudo em UTC)."""
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def build_query(filters: TenderFilters, tz: ZoneInfo, now: datetime) -> TenderQuery:
    """As datas do filtro são dias no fuso de exibição (padrão: Brasília): "publicadas em
    22/11" significa de 22/11 00:00 até 23/11 00:00 nesse fuso."""
    return TenderQuery(
        text=filters.q,
        state=filters.state,
        municipality_ibge_code=filters.municipality,
        modality_code=filters.modality,
        min_value=filters.min_value,
        max_value=filters.max_value,
        published_since=(
            _start_of_day(filters.published_from, tz) if filters.published_from else None
        ),
        published_before=(
            _start_of_day(filters.published_to + timedelta(days=1), tz)
            if filters.published_to
            else None
        ),
        open_at=now if filters.open_only else None,
    )


def proposals_open(tender: Tender, now: datetime) -> bool:
    """Prazo de propostas não encerrado (inclui o que ainda vai começar)."""
    return tender.proposals_close_at is not None and tender.proposals_close_at > now


# Campos das respostas que não são colunas de Tender e são preenchidos à parte.
_DERIVED = {
    "agency",
    "agency_name",
    "proposals_open",
    "process_number",
    "legal_basis",
    "dispute_mode",
    "complementary_info",
    "origin_system_url",
}


def _columns(tender: Tender, schema: type[TenderSummary]) -> dict[str, object]:
    return {name: getattr(tender, name) for name in schema.model_fields if name not in _DERIVED}


def to_summary(tender: Tender, now: datetime) -> TenderSummary:
    return TenderSummary.model_validate(
        _columns(tender, TenderSummary)
        | {"agency_name": tender.agency.name, "proposals_open": proposals_open(tender, now)}
    )


def to_detail(tender: Tender, now: datetime) -> TenderDetail:
    return TenderDetail.model_validate(
        _columns(tender, TenderDetail)
        | {
            "agency": AgencyOut.model_validate(tender.agency),
            "agency_name": tender.agency.name,
            "proposals_open": proposals_open(tender, now),
        }
        | _raw_extras(tender.raw_data or {}, tender.object_description)
    )


def _text(value: object) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _safe_url(value: object) -> str | None:
    """Só links http(s): o valor vem de fora e vai para um href (evita "javascript:")."""
    url = _text(value)
    if url and url.lower().startswith(("https://", "http://")):
        return url
    return None


def _raw_extras(raw: dict[str, Any], object_description: str) -> dict[str, str | None]:
    complementary = _text(raw.get("informacaoComplementar"))
    legal_basis = raw.get("amparoLegal")
    return {
        "process_number": _text(raw.get("processo")),
        "legal_basis": _text(legal_basis.get("nome")) if isinstance(legal_basis, dict) else None,
        "dispute_mode": _text(raw.get("modoDisputaNome")),
        # Muitos órgãos repetem o objeto aqui; só mostramos quando acrescenta algo.
        "complementary_info": (
            complementary if complementary != object_description.strip() else None
        ),
        "origin_system_url": _safe_url(raw.get("linkSistemaOrigem")),
    }


def search(
    session: Session, filters: TenderFilters, tz: ZoneInfo, now: datetime | None = None
) -> TenderPage:
    now = now or datetime.now(UTC)
    items, total = repository.search_tenders(
        session,
        build_query(filters, tz, now),
        limit=filters.page_size,
        offset=(filters.page - 1) * filters.page_size,
    )
    return TenderPage(
        items=[to_summary(item, now) for item in items],
        total=total,
        page=filters.page,
        page_size=filters.page_size,
    )


def get_detail(
    session: Session, tender_id: int, now: datetime | None = None
) -> TenderDetail | None:
    tender = repository.get_tender(session, tender_id)
    return to_detail(tender, now or datetime.now(UTC)) if tender else None


def municipalities(session: Session, state: str | None = None) -> list[tuple[str, str]]:
    return repository.list_municipalities(session, state)


def states(session: Session) -> list[str]:
    return repository.list_states(session)
