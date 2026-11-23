"""Resumo das licitações encontradas pelos alertas, por e-mail e Telegram.

Cada canal tem a própria marca de envio em alert_matches: uma licitação só sai uma vez
por canal para cada alerta. A marca é gravada depois do envio bem-sucedido; se o envio
falhar, a licitação continua pendente e vai no próximo resumo.
"""

import html
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from jinja2 import Environment
from sqlalchemy.orm import Session

from app.api.templating import get_templates, timezone_label
from app.formatting import format_brl, format_datetime
from app.models import Alert, AlertMatch
from app.notifiers.email import EmailError, EmailSender, build_message
from app.notifiers.telegram import TelegramClient, TelegramError, split_message
from app.repositories import alerts as repository
from app.repositories.alerts import Channel

logger = logging.getLogger(__name__)


@dataclass
class DigestReport:
    emails_sent: int = 0
    telegram_messages_sent: int = 0
    tenders_notified: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


@dataclass(frozen=True, slots=True)
class DigestContext:
    base_url: str
    tz: ZoneInfo
    sender: str

    def detail_url(self, tender_id: int) -> str:
        return f"{self.base_url.rstrip('/')}/licitacoes/{tender_id}"


def _subject(alert: Alert, count: int) -> str:
    noun = "nova licitação" if count == 1 else "novas licitações"
    return f"Radar de Licitações: {count} {noun} para “{alert.name}”"


def render_email(
    env: Environment, alert: Alert, matches: list[AlertMatch], ctx: DigestContext
) -> tuple[str, str, str]:
    """(assunto, texto, html) do resumo de um alerta."""
    context = {
        "alert": alert,
        "matches": matches,
        "detail_url": ctx.detail_url,
        "alerts_url": f"{ctx.base_url.rstrip('/')}/admin/alertas",
        "tz_label": timezone_label(ctx.tz),
    }
    text = env.get_template("emails/digest.txt").render(context)
    body = env.get_template("emails/digest.html").render(context)
    return _subject(alert, len(matches)), text, body


def render_telegram(alert: Alert, matches: list[AlertMatch], ctx: DigestContext) -> list[str]:
    """Mensagens HTML do Telegram (divididas para caber no limite de tamanho)."""
    esc = html.escape
    header = f"<b>{esc(_subject(alert, len(matches)))}</b>"
    blocks = [header]
    for match in matches:
        tender = match.tender
        link = esc(ctx.detail_url(tender.id))
        lines = [
            f'<a href="{link}">{esc(tender.object_description[:300])}</a>',
            f"{esc(tender.municipality_name)}/{esc(tender.state)} · {esc(tender.modality_name)}",
            f"Valor estimado: {esc(format_brl(tender.estimated_value))}",
        ]
        if tender.proposals_close_at:
            close = format_datetime(tender.proposals_close_at, ctx.tz)
            lines.append(f"Propostas até {close} ({esc(timezone_label(ctx.tz))})")
        blocks.append("\n".join(lines))
    return split_message(blocks)


def _send_email(
    session: Session,
    alert: Alert,
    sender: EmailSender,
    ctx: DigestContext,
    report: DigestReport,
    now: datetime,
) -> None:
    matches = repository.pending_matches(session, alert.id, Channel.EMAIL)
    if not matches:
        return
    subject, text, body = render_email(get_templates().env, alert, matches, ctx)
    message = build_message(
        sender=ctx.sender, to=alert.email, subject=subject, text=text, html=body
    )
    try:
        sender.send(message)
    except EmailError as exc:
        report.failures.append(f"e-mail do alerta {alert.id}: {exc}")
        logger.error(
            "Falha ao enviar resumo por e-mail", extra={"alert_id": alert.id, "error": str(exc)}
        )
        return
    repository.mark_sent(session, [m.id for m in matches], Channel.EMAIL, now)
    session.commit()
    report.emails_sent += 1
    report.tenders_notified += len(matches)
    logger.info("Resumo enviado por e-mail", extra={"alert_id": alert.id, "tenders": len(matches)})


def _send_telegram(
    session: Session,
    alert: Alert,
    client: TelegramClient,
    ctx: DigestContext,
    report: DigestReport,
    now: datetime,
) -> None:
    assert alert.telegram_chat_id is not None
    matches = repository.pending_matches(session, alert.id, Channel.TELEGRAM)
    if not matches:
        return
    messages = render_telegram(alert, matches, ctx)
    try:
        for text in messages:
            client.send_message(alert.telegram_chat_id, text)
    except TelegramError as exc:
        # Mensagens já entregues deste resumo podem se repetir na próxima tentativa; é
        # preferível a perder licitações marcando como enviadas as que não saíram.
        report.failures.append(f"Telegram do alerta {alert.id}: {exc}")
        logger.error(
            "Falha ao enviar resumo pelo Telegram", extra={"alert_id": alert.id, "error": str(exc)}
        )
        return
    repository.mark_sent(session, [m.id for m in matches], Channel.TELEGRAM, now)
    session.commit()
    report.telegram_messages_sent += len(messages)
    logger.info(
        "Resumo enviado pelo Telegram", extra={"alert_id": alert.id, "tenders": len(matches)}
    )


def send_digests(
    session: Session,
    *,
    email_sender: EmailSender | None,
    telegram: TelegramClient | None,
    ctx: DigestContext,
    now: datetime | None = None,
) -> DigestReport:
    """Envia, para cada alerta ativo, as licitações ainda não notificadas em cada canal."""
    now = now or datetime.now(UTC)
    report = DigestReport()
    if email_sender is None:
        logger.warning("SMTP não configurado: resumos por e-mail não serão enviados")
    else:
        for alert in repository.alerts_with_pending(session, Channel.EMAIL):
            _send_email(session, alert, email_sender, ctx, report, now)
    if telegram is not None:
        for alert in repository.alerts_with_pending(session, Channel.TELEGRAM):
            _send_telegram(session, alert, telegram, ctx, report, now)
    logger.info(
        "Envio de resumos concluído",
        extra={
            "emails_sent": report.emails_sent,
            "telegram_messages_sent": report.telegram_messages_sent,
            "failures": len(report.failures),
        },
    )
    return report
