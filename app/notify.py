"""Envia os resumos de alertas pendentes (e-mail e, se configurado, Telegram).

    python -m app.notify

Sai com código 0 se tudo foi enviado e 1 se algum envio falhou (o que falhou continua
pendente e vai na próxima execução).
"""

import argparse
import sys
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db import get_sessionmaker
from app.logging_config import configure_logging
from app.notifiers.email import SmtpEmailSender
from app.notifiers.telegram import TelegramClient
from app.services.notifications import DigestContext, send_digests


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="python -m app.notify",
        description="Envia os resumos das licitações encontradas pelos alertas.",
    ).parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    ctx = DigestContext(
        settings.app_base_url, ZoneInfo(settings.display_timezone), settings.smtp_from
    )
    telegram = TelegramClient.from_settings(settings)
    try:
        with get_sessionmaker()() as session:
            report = send_digests(
                session,
                email_sender=SmtpEmailSender.from_settings(settings),
                telegram=telegram,
                ctx=ctx,
            )
    finally:
        if telegram is not None:
            telegram.close()
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
