"""Acesso aos alertas e ao cruzamento alertas x licitações (alert_matches)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    ColumnElement,
    String,
    and_,
    any_,
    cast,
    delete,
    exists,
    func,
    literal_column,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, array, insert
from sqlalchemy.orm import InstrumentedAttribute, Session, joinedload

from app.models import Alert, AlertMatch, Tender
from app.models.tender import SEARCH_CONFIG

_REGCONFIG = literal_column(f"'{SEARCH_CONFIG}'::regconfig")


class Channel(StrEnum):
    EMAIL = "email"
    TELEGRAM = "telegram"


_SENT_COLUMN: dict[Channel, InstrumentedAttribute[datetime | None]] = {
    Channel.EMAIL: AlertMatch.notified_at,
    Channel.TELEGRAM: AlertMatch.telegram_notified_at,
}


@dataclass(frozen=True, slots=True)
class AlertStats:
    alert: Alert
    matches: int
    pending_email: int
    last_match_at: datetime | None


# --- CRUD ------------------------------------------------------------------------------


def list_with_stats(session: Session) -> list[AlertStats]:
    pending = func.count(AlertMatch.id).filter(AlertMatch.notified_at.is_(None))
    stmt = (
        select(Alert, func.count(AlertMatch.id), pending, func.max(AlertMatch.matched_at))
        .outerjoin(AlertMatch)
        .group_by(Alert.id)
        .order_by(Alert.active.desc(), func.lower(Alert.name))
    )
    return [AlertStats(*row) for row in session.execute(stmt).tuples()]


def get(session: Session, alert_id: int) -> Alert | None:
    return session.get(Alert, alert_id)


def delete_unsent_matches(session: Session, alert_id: int) -> None:
    """Remove casamentos ainda não enviados por nenhum canal (antes de recalcular)."""
    session.execute(
        delete(AlertMatch).where(
            AlertMatch.alert_id == alert_id,
            AlertMatch.notified_at.is_(None),
            AlertMatch.telegram_notified_at.is_(None),
        )
    )


def recent_matches(session: Session, alert_id: int, limit: int = 50) -> list[AlertMatch]:
    stmt = (
        select(AlertMatch)
        .options(joinedload(AlertMatch.tender))
        .where(AlertMatch.alert_id == alert_id)
        .order_by(AlertMatch.matched_at.desc(), AlertMatch.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def ineffective_keywords(session: Session, keywords: Sequence[str]) -> list[str]:
    """Palavras-chave que viram busca vazia (só palavras como "de", "para")."""
    if not keywords:
        return []
    keyword = func.unnest(literal_list(keywords)).alias("kw")
    stmt = (
        select(literal_column("kw"))
        .select_from(keyword)
        .where(func.numnode(func.websearch_to_tsquery(_REGCONFIG, literal_column("kw"))) == 0)
    )
    return list(session.scalars(stmt))


def literal_list(values: Sequence[str]) -> ColumnElement[list[str]]:
    return cast(array(list(values)), ARRAY(String))


# --- Cruzamento ------------------------------------------------------------------------


def _match_conditions() -> list[ColumnElement[bool]]:
    """Regras de um alerta valer para uma licitação (Alert x Tender)."""
    keyword = func.unnest(Alert.keywords).alias("kw")
    keyword_matches = exists(
        select(1)
        .select_from(keyword)
        .where(
            Tender.search_vector.op("@@")(
                func.websearch_to_tsquery(_REGCONFIG, literal_column("kw"))
            )
        )
    )
    in_scope = or_(
        and_(func.cardinality(Alert.states) == 0, func.cardinality(Alert.municipalities) == 0),
        Tender.state == any_(Alert.states),
        Tender.municipality_ibge_code == any_(Alert.municipalities),
    )
    # Licitação sem valor estimado entra: é melhor avisar a mais do que perder uma.
    in_value_range = and_(
        or_(
            Alert.min_value.is_(None),
            Tender.estimated_value.is_(None),
            Tender.estimated_value >= Alert.min_value,
        ),
        or_(
            Alert.max_value.is_(None),
            Tender.estimated_value.is_(None),
            Tender.estimated_value <= Alert.max_value,
        ),
    )
    return [Alert.active.is_(True), in_scope, in_value_range, keyword_matches]


def create_matches(
    session: Session,
    *,
    tenders_created_since: datetime | None = None,
    proposals_open_at: datetime | None = None,
    alert_id: int | None = None,
) -> int:
    """Grava em alert_matches os pares (alerta ativo, licitação) que casam.

    Pares já existentes são ignorados (ON CONFLICT DO NOTHING): rodar de novo não duplica
    nem "desnotifica" nada. Devolve quantos casamentos novos foram criados.
    """
    conditions = _match_conditions()
    if tenders_created_since is not None:
        conditions.append(Tender.created_at >= tenders_created_since)
    if proposals_open_at is not None:
        conditions.append(Tender.proposals_close_at > proposals_open_at)
    if alert_id is not None:
        conditions.append(Alert.id == alert_id)

    pairs = select(Alert.id, Tender.id).where(*conditions)
    stmt = (
        insert(AlertMatch)
        .from_select(["alert_id", "tender_id"], pairs)
        .on_conflict_do_nothing(index_elements=["alert_id", "tender_id"])
        .returning(AlertMatch.id)
    )
    return len(session.execute(stmt).scalars().all())


# --- Notificação -----------------------------------------------------------------------


def alerts_with_pending(session: Session, channel: Channel) -> list[Alert]:
    sent = _SENT_COLUMN[channel]
    conditions = [Alert.active.is_(True)]
    if channel is Channel.TELEGRAM:
        conditions.append(Alert.telegram_chat_id.is_not(None))
    stmt = (
        select(Alert)
        .where(
            *conditions,
            exists().where(AlertMatch.alert_id == Alert.id, sent.is_(None)),
        )
        .order_by(Alert.id)
    )
    return list(session.scalars(stmt))


def pending_matches(session: Session, alert_id: int, channel: Channel) -> list[AlertMatch]:
    """Casamentos ainda não enviados pelo canal; prazos mais próximos primeiro."""
    stmt = (
        select(AlertMatch)
        .join(AlertMatch.tender)
        .options(joinedload(AlertMatch.tender).joinedload(Tender.agency))
        .where(AlertMatch.alert_id == alert_id, _SENT_COLUMN[channel].is_(None))
        .order_by(
            Tender.proposals_close_at.asc().nulls_last(),
            Tender.published_at.desc(),
            Tender.id,
        )
    )
    return list(session.scalars(stmt))


def mark_sent(
    session: Session, match_ids: Sequence[int], channel: Channel, sent_at: datetime
) -> None:
    sent = _SENT_COLUMN[channel]
    session.execute(
        update(AlertMatch)
        .where(AlertMatch.id.in_(match_ids), sent.is_(None))
        .values({sent.key: sent_at})
    )
