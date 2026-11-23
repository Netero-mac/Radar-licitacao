"""Aviso ao administrador quando as coletas automáticas falham seguidas vezes.

Uma execução do agendador "teve problema" quando a coleta falhou ou quando algum resumo
não pôde ser enviado. Depois de ``ADMIN_ALERT_AFTER_FAILURES`` execuções seguidas com
problema, o administrador recebe **um** aviso; quando uma execução volta a dar certo,
recebe outro dizendo que normalizou. Nada é repetido a cada horário enquanto o problema
continua.

Só as execuções do agendador contam: quem aperta "Coletar agora" ou roda o CLI já vê o
resultado na hora. O aviso vai por e-mail e/ou Telegram; configurar os dois cobre o caso
em que o próprio SMTP é o problema.
"""

import html
import logging
from collections.abc import Sequence
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import Settings
from app.formatting import format_datetime
from app.models import CollectionRun, CollectionStatus, CollectionTrigger
from app.notifiers.email import EmailError, EmailSender, build_message
from app.notifiers.telegram import TelegramClient, TelegramError
from app.repositories import collection_runs

logger = logging.getLogger(__name__)

MAX_LISTED_FAILURES = 3


class AdminAlert(StrEnum):
    FAILING = "failing"
    RECOVERED = "recovered"


def has_problem(run: CollectionRun) -> bool:
    return run.status == CollectionStatus.FAILED or (run.notification_failures or 0) > 0


def failure_streak(runs: Sequence[CollectionRun]) -> int:
    """Quantas execuções seguidas, a partir da mais recente, tiveram problema."""
    streak = 0
    for run in runs:
        if not has_problem(run):
            break
        streak += 1
    return streak


def current_streak(session: Session, limit: int = 50) -> int:
    return failure_streak(collection_runs.recent_scheduled_runs(session, limit))


def decide(runs: Sequence[CollectionRun], threshold: int) -> AdminAlert | None:
    """O que avisar depois da execução mais recente (``runs[0]``)."""
    if not runs:
        return None
    if has_problem(runs[0]):
        # Exatamente no limite: um aviso só, não um por horário.
        return AdminAlert.FAILING if failure_streak(runs) == threshold else None
    return AdminAlert.RECOVERED if failure_streak(runs[1:]) >= threshold else None


def _lines(
    kind: AdminAlert, run: CollectionRun, failures: Sequence[str], settings: Settings
) -> tuple[str, list[str]]:
    when = format_datetime(run.started_at, ZoneInfo(settings.display_timezone))
    link = f"{settings.app_base_url.rstrip('/')}/admin/coletas"
    if kind is AdminAlert.RECOVERED:
        return "Radar de Licitações: coletas automáticas normalizadas", [
            f"A coleta automática de {when} terminou sem erros, depois de "
            f"{settings.admin_alert_after_failures} ou mais seguidas com problema.",
            f"Histórico: {link}",
        ]
    lines = [
        f"As últimas {settings.admin_alert_after_failures} coletas automáticas do Radar de "
        "Licitações tiveram problema.",
        f"Última: {when}.",
    ]
    if run.status == CollectionStatus.FAILED:
        lines.append(f"Erro na coleta: {run.error_message or 'sem detalhes'}")
    if failures:
        shown = "; ".join(failures[:MAX_LISTED_FAILURES])
        more = len(failures) - MAX_LISTED_FAILURES
        lines.append(
            f"Falhas no envio dos resumos ({len(failures)}): {shown}"
            + (f" (e mais {more})" if more > 0 else "")
        )
    lines += [
        f"Histórico: {link}",
        "Você não recebe outro aviso enquanto o problema continuar; avisamos quando normalizar.",
    ]
    return "Radar de Licitações: coletas automáticas com problema", lines


def notify_after_cycle(
    session: Session,
    run: CollectionRun,
    *,
    settings: Settings,
    email_sender: EmailSender | None,
    telegram: TelegramClient | None,
    digest_failures: Sequence[str] = (),
) -> AdminAlert | None:
    """Depois de uma execução do agendador: avisa o administrador, se for o caso.

    Falhas no próprio aviso só vão para o log; nunca derrubam o ciclo.
    """
    email_to = settings.admin_alert_email
    chat_id = settings.admin_alert_telegram_chat_id
    if run.trigger != CollectionTrigger.SCHEDULED or not (email_to or chat_id):
        return None
    threshold = settings.admin_alert_after_failures
    kind = decide(collection_runs.recent_scheduled_runs(session, threshold + 1), threshold)
    if kind is None:
        return None

    subject, lines = _lines(kind, run, digest_failures, settings)
    sent = False
    if email_to and email_sender is not None:
        message = build_message(
            sender=settings.smtp_from,
            to=email_to,
            subject=subject,
            text="\n\n".join(lines),
            html="".join(f"<p>{html.escape(line)}</p>" for line in lines),
        )
        try:
            email_sender.send(message)
            sent = True
        except EmailError:
            logger.exception("Falha ao enviar o aviso ao administrador por e-mail")
    if chat_id and telegram is not None:
        text = f"<b>{html.escape(subject)}</b>\n\n" + "\n\n".join(html.escape(x) for x in lines)
        try:
            telegram.send_message(chat_id, text)
            sent = True
        except TelegramError:
            logger.exception("Falha ao enviar o aviso ao administrador pelo Telegram")

    log = logger.warning if kind is AdminAlert.FAILING else logger.info
    log(
        "Aviso ao administrador: coletas com problema"
        if kind is AdminAlert.FAILING
        else "Aviso ao administrador: coletas normalizadas",
        extra={"run_id": run.id, "sent": sent},
    )
    return kind
