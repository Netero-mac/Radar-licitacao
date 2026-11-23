"""Registro das execuções da coleta (tabela collection_runs)."""

from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import CollectionRun, CollectionStatus, CollectionTrigger


def start_run(
    session: Session,
    *,
    trigger: CollectionTrigger,
    date_from: date,
    date_to: date,
    states: Sequence[str] = (),
) -> CollectionRun:
    run = CollectionRun(
        trigger=trigger,
        states=list(states),
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


def recent_runs(session: Session, limit: int = 20) -> list[CollectionRun]:
    stmt = select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def recent_scheduled_runs(session: Session, limit: int) -> list[CollectionRun]:
    """Execuções do agendador já terminadas, da mais recente para a mais antiga."""
    stmt = (
        select(CollectionRun)
        .where(
            CollectionRun.trigger == CollectionTrigger.SCHEDULED,
            CollectionRun.status != CollectionStatus.RUNNING,
        )
        .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def fail_interrupted_runs(session: Session) -> int:
    """Marca como falhas as coletas que ficaram "em andamento" (processo interrompido).

    Só pode ser chamado com a trava de coleta em mãos: aí nenhuma outra está rodando.
    """
    result = session.execute(
        update(CollectionRun)
        .where(CollectionRun.status == CollectionStatus.RUNNING)
        .values(
            status=CollectionStatus.FAILED,
            finished_at=func.now(),
            error_message="Coleta interrompida antes de terminar (processo encerrado).",
        )
    )
    return result.rowcount or 0
