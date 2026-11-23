"""Coleta de contratações do PNCP: busca na API, grava no banco e registra a execução."""

import logging
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.collectors.pncp import PncpClient, PncpPage, PncpTender
from app.collectors.pncp.schemas import agency_values, tender_values
from app.models import CollectionRun, CollectionStatus, CollectionTrigger
from app.repositories import collection_runs, tenders
from app.repositories.tenders import UpsertResult

logger = logging.getLogger(__name__)


def default_period(lookback_days: int, tz: ZoneInfo) -> tuple[date, date]:
    """Hoje e os dias anteriores, num total de ``lookback_days`` dias (datas inclusivas).

    Coletar mais de um dia a cada execução evita perder o que foi publicado perto da
    meia-noite ou durante uma indisponibilidade da API; o upsert impede duplicatas.
    """
    today = datetime.now(tz).date()
    return today - timedelta(days=lookback_days - 1), today


def _parse_items(items: list[dict[str, Any]]) -> list[tuple[PncpTender, dict[str, Any]]]:
    """Valida os itens da página; um registro malformado é ignorado, sem derrubar a coleta."""
    parsed = []
    for raw in items:
        try:
            tender = PncpTender.model_validate(raw)
            tender.sphere()
        except (ValidationError, ValueError) as exc:
            logger.warning(
                "Registro do PNCP ignorado por estar fora do formato esperado",
                extra={"pncp_control_number": raw.get("numeroControlePNCP"), "error": str(exc)},
            )
            continue
        parsed.append((tender, raw))
    return parsed


def store_page(session: Session, page: PncpPage, source_tz: ZoneInfo) -> UpsertResult:
    parsed = _parse_items(page.items)
    agency_ids = tenders.upsert_agencies(session, [agency_values(t) for t, _ in parsed])
    rows = [
        tender_values(t, raw, agency_ids[t.orgao_entidade.cnpj], source_tz) for t, raw in parsed
    ]
    return tenders.upsert_tenders(session, rows)


def run_collection(
    session: Session,
    client: PncpClient,
    *,
    date_from: date,
    date_to: date,
    state: str,
    modalities: Sequence[int],
    source_tz: ZoneInfo,
    trigger: CollectionTrigger,
) -> CollectionRun:
    """Executa uma coleta completa e devolve o registro em collection_runs.

    Cada página é gravada e confirmada (commit) assim que chega: se a API cair no meio,
    o que já veio fica salvo e a próxima execução completa o resto. Falhas não são
    propagadas: ficam registradas na execução com status "failed".
    """
    if date_from > date_to:
        raise ValueError("a data inicial não pode ser posterior à data final")

    run = collection_runs.start_run(session, trigger=trigger, date_from=date_from, date_to=date_to)
    session.commit()
    log_extra: dict[str, Any] = {
        "run_id": run.id,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "state": state,
    }
    logger.info("Coleta iniciada", extra=log_extra)

    try:
        for modality in modalities:
            for page in client.iter_published(date_from, date_to, modality, state):
                result = store_page(session, page, source_tz)
                collection_runs.add_page_stats(run, new=result.new, updated=result.updated)
                session.commit()
                logger.info(
                    "Página gravada",
                    extra={
                        **log_extra,
                        "modality": modality,
                        "page": page.number,
                        "total_pages": page.total_pages,
                        "new": result.new,
                        "updated": result.updated,
                    },
                )
    except Exception as exc:
        session.rollback()
        collection_runs.finish_run(run, CollectionStatus.FAILED, error_message=str(exc))
        session.commit()
        session.refresh(run)  # o rollback expirou os contadores; recarrega o que foi salvo
        logger.exception("Coleta falhou", extra=log_extra)
        return run

    collection_runs.finish_run(run, CollectionStatus.SUCCESS)
    session.commit()
    logger.info(
        "Coleta concluída",
        extra={
            **log_extra,
            "pages_fetched": run.pages_fetched,
            "tenders_new": run.tenders_new,
            "tenders_updated": run.tenders_updated,
        },
    )
    return run
