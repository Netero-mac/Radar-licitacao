from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage

import httpx
import respx
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import CollectionRun, CollectionStatus, CollectionTrigger
from app.notifiers.email import EmailError
from app.notifiers.telegram import TelegramClient
from app.repositories import collection_runs
from app.services.admin_alerts import AdminAlert, current_streak, notify_after_cycle

TELEGRAM_API = "https://telegram.test"
TOKEN = "123:abc"
START = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


class FakeSender:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[EmailMessage] = []
        self.fail = fail

    def send(self, message: EmailMessage) -> None:
        if self.fail:
            raise EmailError("SMTP fora do ar")
        self.sent.append(message)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql://x",
        "app_base_url": "https://radar.exemplo.com.br",
        "admin_alert_email": "admin@exemplo.com.br",
    }
    return Settings(_env_file=None, **(values | overrides))  # type: ignore[call-arg]


def _notify(
    session: Session, run: CollectionRun, sender: FakeSender, settings: Settings | None = None
) -> AdminAlert | None:
    return notify_after_cycle(
        session, run, settings=settings or _settings(), email_sender=sender, telegram=None
    )


def _run(
    session: Session,
    index: int,
    *,
    failed: bool = False,
    send_failures: int | None = 0,
    trigger: CollectionTrigger = CollectionTrigger.SCHEDULED,
) -> CollectionRun:
    run = collection_runs.start_run(
        session, trigger=trigger, date_from=date(2026, 11, 19), date_to=date(2026, 11, 20)
    )
    run.started_at = START + timedelta(hours=11 * index)
    collection_runs.finish_run(
        run,
        CollectionStatus.FAILED if failed else CollectionStatus.SUCCESS,
        error_message="PNCP respondeu 500 após 6 tentativas" if failed else None,
    )
    run.notification_failures = send_failures
    session.flush()
    return run


def _text(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",))
    assert part is not None
    return part.get_content()


def test_avisa_uma_vez_quando_chega_ao_limite(db_session: Session) -> None:
    sender = FakeSender()
    settings = _settings()

    first = _run(db_session, 0, failed=True)
    assert (
        notify_after_cycle(db_session, first, settings=settings, email_sender=sender, telegram=None)
        is None
    )

    second = _run(db_session, 1, failed=True)
    kind = notify_after_cycle(
        db_session, second, settings=settings, email_sender=sender, telegram=None
    )
    assert kind is AdminAlert.FAILING

    third = _run(db_session, 2, failed=True)
    assert (
        notify_after_cycle(db_session, third, settings=settings, email_sender=sender, telegram=None)
        is None
    )

    assert len(sender.sent) == 1
    message = sender.sent[0]
    assert message["To"] == "admin@exemplo.com.br"
    assert message["Subject"] == "Radar de Licitações: coletas automáticas com problema"
    text = _text(message)
    assert "As últimas 2 coletas automáticas" in text
    assert "Erro na coleta: PNCP respondeu 500 após 6 tentativas" in text
    assert "https://radar.exemplo.com.br/admin/coletas" in text
    assert current_streak(db_session) == 3


def test_falha_no_envio_dos_resumos_conta_e_aparece_no_aviso(db_session: Session) -> None:
    sender = FakeSender()
    _run(db_session, 0, send_failures=1)
    run = _run(db_session, 1, send_failures=5)
    failures = [f"e-mail do alerta {n}: conexão recusada" for n in range(5)]

    kind = notify_after_cycle(
        db_session, run, settings=_settings(), email_sender=sender, telegram=None,
        digest_failures=failures,
    )  # fmt: skip

    assert kind is AdminAlert.FAILING
    text = _text(sender.sent[0])
    assert "Falhas no envio dos resumos (5): e-mail do alerta 0" in text
    assert "(e mais 2)" in text
    assert "Erro na coleta" not in text


def test_avisa_quando_normaliza(db_session: Session) -> None:
    sender = FakeSender()
    _run(db_session, 0, failed=True)
    _run(db_session, 1, failed=True)
    ok = _run(db_session, 2)

    kind = notify_after_cycle(
        db_session, ok, settings=_settings(), email_sender=sender, telegram=None
    )

    assert kind is AdminAlert.RECOVERED
    assert sender.sent[0]["Subject"] == "Radar de Licitações: coletas automáticas normalizadas"
    assert current_streak(db_session) == 0


def test_so_as_execucoes_do_agendador_contam(db_session: Session) -> None:
    sender = FakeSender()
    _run(db_session, 0, failed=True)
    manual = _run(db_session, 1, failed=True, trigger=CollectionTrigger.MANUAL, send_failures=None)

    assert (
        notify_after_cycle(
            db_session, manual, settings=_settings(), email_sender=sender, telegram=None
        )
        is None
    )
    scheduled = _run(db_session, 2, failed=True)
    assert _notify(db_session, scheduled, sender) is AdminAlert.FAILING
    assert len(sender.sent) == 1


def test_desativado_sem_destino(db_session: Session) -> None:
    sender = FakeSender()
    settings = _settings(admin_alert_email=None)
    _run(db_session, 0, failed=True)
    run = _run(db_session, 1, failed=True)

    assert (
        notify_after_cycle(db_session, run, settings=settings, email_sender=sender, telegram=None)
        is None
    )
    assert sender.sent == []


def test_telegram_avisa_mesmo_com_o_smtp_fora(db_session: Session) -> None:
    settings = _settings(admin_alert_telegram_chat_id="999")
    _run(db_session, 0, failed=True)
    run = _run(db_session, 1, failed=True)
    telegram = TelegramClient(TOKEN, api_url=TELEGRAM_API)

    with respx.mock(base_url=TELEGRAM_API) as api:
        route = api.post(f"/bot{TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        kind = notify_after_cycle(
            db_session, run, settings=settings, email_sender=FakeSender(fail=True),
            telegram=telegram,
        )  # fmt: skip
    telegram.close()

    assert kind is AdminAlert.FAILING
    body = route.calls.last.request.read().decode()
    assert '"chat_id":"999"' in body.replace(" ", "")
    assert "coletas autom" in body
