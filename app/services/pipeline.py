"""O ciclo completo: coleta no PNCP -> cruzamento com os alertas -> resumos.

Usado pelo agendador (7h e 18h), pelo botão "Coletar agora" (sem os resumos) e pelo
CLI de coleta. Tudo roda sob a trava de coleta: se outra execução estiver em
andamento, esta é pulada em vez de esperar ou duplicar trabalho.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from app.collectors.pncp import PncpClient
from app.config import Settings
from app.models import CollectionRun, CollectionStatus, CollectionTrigger
from app.notifiers.email import SmtpEmailSender
from app.notifiers.telegram import TelegramClient
from app.repositories import collection_runs
from app.services.alerts import match_new_tenders
from app.services.collection import default_period, run_collection
from app.services.locks import collection_lock
from app.services.notifications import DigestContext, DigestReport, send_digests

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineResult:
    skipped: bool = False  # outra coleta em andamento
    run: CollectionRun | None = None
    matches: int = 0
    digest: DigestReport | None = None

    @property
    def ok(self) -> bool:
        if self.skipped or self.run is None:
            return False
        digest_ok = self.digest is None or self.digest.ok
        return self.run.status == CollectionStatus.SUCCESS and digest_ok


def run_pipeline(
    settings: Settings,
    sessions: sessionmaker[Session],
    *,
    trigger: CollectionTrigger,
    send_notifications: bool,
    date_from: date | None = None,
    date_to: date | None = None,
    states: list[str] | None = None,
    modalities: list[int] | None = None,
    client_factory: Callable[[Settings], PncpClient] = PncpClient.from_settings,
) -> PipelineResult:
    source_tz = ZoneInfo(settings.pncp_timezone)
    default_from, default_to = default_period(settings.collection_lookback_days, source_tz)
    engine = sessions.kw["bind"]
    with collection_lock(engine) as acquired:
        if not acquired:
            logger.warning(
                "Coleta ignorada: outra coleta está em andamento", extra={"trigger": trigger.value}
            )
            return PipelineResult(skipped=True)

        with sessions() as session:
            interrupted = collection_runs.fail_interrupted_runs(session)
            session.commit()
            if interrupted:
                logger.warning(
                    "Coletas interrompidas marcadas como falha", extra={"count": interrupted}
                )

            with client_factory(settings) as client:
                run = run_collection(
                    session,
                    client,
                    date_from=date_from or default_from,
                    date_to=date_to or default_to,
                    states=states if states is not None else settings.pncp_states,
                    modalities=modalities or settings.pncp_modalities,
                    source_tz=source_tz,
                    trigger=trigger,
                )
            # Mesmo numa coleta que falhou no meio, as páginas salvas podem casar com alertas.
            matches = match_new_tenders(session, created_since=run.started_at)

            digest = None
            if send_notifications:
                digest = _send_digests(settings, session)
    return PipelineResult(run=run, matches=matches, digest=digest)


def _send_digests(settings: Settings, session: Session) -> DigestReport:
    ctx = DigestContext(
        settings.app_base_url, ZoneInfo(settings.display_timezone), settings.smtp_from
    )
    telegram = TelegramClient.from_settings(settings)
    try:
        return send_digests(
            session,
            email_sender=SmtpEmailSender.from_settings(settings),
            telegram=telegram,
            ctx=ctx,
        )
    finally:
        if telegram is not None:
            telegram.close()
