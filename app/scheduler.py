"""Agendador: roda o ciclo completo (coleta -> alertas -> resumos) nos horários do .env.

    python -m app.scheduler            # fica rodando (serviço "scheduler" do Compose)
    python -m app.scheduler --agora    # executa o ciclo uma vez e sai

Horários em SCHEDULE_HOURS (padrão 7 e 18) no fuso SCHEDULE_TIMEZONE (padrão
America/Cuiaba). Se a máquina estava desligada no horário, o ciclo roda assim que o
agendador voltar, desde que dentro de 1 hora; execuções atrasadas não se acumulam.
"""

import argparse
import logging
import signal
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from types import FrameType
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.logging_config import configure_logging
from app.models import CollectionTrigger
from app.services.pipeline import PipelineResult, run_pipeline

logger = logging.getLogger("app.scheduler")

JOB_ID = "ciclo-completo"
MISFIRE_GRACE_SECONDS = 3600


def scheduled_cycle(settings: Settings) -> PipelineResult:
    """Um ciclo agendado. Erros são registrados no log e não derrubam o agendador."""
    try:
        result = run_pipeline(
            settings,
            get_sessionmaker(),
            trigger=CollectionTrigger.SCHEDULED,
            send_notifications=True,
        )
    except Exception:
        logger.exception("Falha no ciclo agendado")
        return PipelineResult()
    if result.skipped:
        return result
    digest = result.digest
    logger.info(
        "Ciclo agendado concluído",
        extra={
            "collection": result.run.status.value if result.run else None,
            "tenders_new": result.run.tenders_new if result.run else 0,
            "matches": result.matches,
            "emails": digest.emails_sent if digest else 0,
            "telegram": digest.telegram_messages_sent if digest else 0,
            "failures": len(digest.failures) if digest else 0,
        },
    )
    return result


def _trigger(settings: Settings) -> CronTrigger:
    return CronTrigger(
        hour=",".join(str(hour) for hour in settings.schedule_hours),
        minute=0,
        timezone=settings.schedule_timezone,
    )


def next_scheduled_runs(settings: Settings, now: datetime, count: int = 2) -> list[datetime]:
    """Próximos horários do ciclo agendado (para mostrar no admin)."""
    trigger = _trigger(settings)
    runs: list[datetime] = []
    previous = None
    current = now.astimezone(ZoneInfo(settings.schedule_timezone))
    for _ in range(count):
        fire = trigger.get_next_fire_time(previous, current)
        if fire is None:  # pragma: no cover - cron diário sempre tem próximo horário
            break
        runs.append(fire)
        previous = fire
        current = fire + timedelta(seconds=1)
    return runs


def build_scheduler(settings: Settings) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=settings.schedule_timezone)
    scheduler.add_job(
        scheduled_cycle,
        _trigger(settings),
        args=[settings],
        id=JOB_ID,
        name="Coleta, alertas e resumos",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
    )
    return scheduler


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.scheduler",
        description="Agenda a coleta, o cruzamento com os alertas e o envio dos resumos.",
    )
    parser.add_argument("--agora", action="store_true", help="executa o ciclo uma vez e sai")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    if args.agora:
        return 0 if scheduled_cycle(settings).ok else 1

    scheduler = build_scheduler(settings)

    def stop(signum: int, frame: FrameType | None) -> None:
        logger.info("Encerrando o agendador", extra={"signal": signal.Signals(signum).name})
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, stop)  # docker stop
    signal.signal(signal.SIGINT, stop)
    hours = ", ".join(f"{hour}h" for hour in settings.schedule_hours)
    upcoming = next_scheduled_runs(settings, datetime.now(ZoneInfo(settings.schedule_timezone)), 1)
    logger.info(
        "Agendador iniciado",
        extra={
            "hours": hours,
            "timezone": settings.schedule_timezone,
            "next_run": upcoming[0].isoformat() if upcoming else None,
        },
    )
    scheduler.start()  # bloqueia até o shutdown
    return 0


if __name__ == "__main__":
    sys.exit(main())
