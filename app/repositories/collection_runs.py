"""Registro das execuções da coleta (tabela collection_runs)."""

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models import CollectionRun, CollectionStatus, CollectionTrigger


def start_run(
    session: Session, *, trigger: CollectionTrigger, date_from: date, date_to: date
) -> CollectionRun:
    run = CollectionRun(
        trigger=trigger,
        date_from=date_from,
        date_to=date_to,
        status=CollectionStatus.RUNNING,
        pages_fetched=0,
        tenders_new=0,
        tenders_updated=0,
    )
    session.add(run)
    session.flush()
    return run


def add_page_stats(run: CollectionRun, *, new: int, updated: int) -> None:
    run.pages_fetched += 1
    run.tenders_new += new
    run.tenders_updated += updated


def finish_run(
    run: CollectionRun, status: CollectionStatus, error_message: str | None = None
) -> None:
    run.status = status
    run.error_message = error_message
    run.finished_at = datetime.now(UTC)
