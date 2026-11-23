from unittest.mock import MagicMock

import pytest

from app import notify
from app.services.notifications import DigestReport


@pytest.mark.parametrize(
    ("report", "code"),
    [(DigestReport(emails_sent=2), 0), (DigestReport(failures=["e-mail do alerta 1: x"]), 1)],
)
def test_envia_resumos_e_retorna_codigo(
    monkeypatch: pytest.MonkeyPatch, report: DigestReport, code: int
) -> None:
    send_digests = MagicMock(return_value=report)
    monkeypatch.setattr(notify, "send_digests", send_digests)
    monkeypatch.setattr(notify, "get_sessionmaker", lambda: MagicMock())

    assert notify.main([]) == code

    kwargs = send_digests.call_args.kwargs
    assert kwargs["telegram"] is None  # sem TELEGRAM_BOT_TOKEN
    assert kwargs["ctx"].base_url == "http://localhost:8000"


def test_fecha_o_cliente_do_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    telegram = MagicMock()
    monkeypatch.setattr(notify.TelegramClient, "from_settings", lambda settings: telegram)
    monkeypatch.setattr(notify, "send_digests", MagicMock(return_value=DigestReport()))
    monkeypatch.setattr(notify, "get_sessionmaker", lambda: MagicMock())

    notify.main([])

    telegram.close.assert_called_once()
