import smtplib
from collections.abc import Iterator
from email.message import EmailMessage
from typing import Any, ClassVar

import httpx
import pytest
import respx

from app.config import Settings
from app.notifiers.email import EmailError, SmtpEmailSender, build_message
from app.notifiers.telegram import TelegramClient, TelegramError, split_message

TOKEN = "123456:SEGREDO-DO-BOT"
API = "https://telegram.test"


# --- E-mail ----------------------------------------------------------------------------


def test_mensagem_tem_texto_e_html() -> None:
    message = build_message(
        sender="Radar <radar@exemplo.com>",
        to="compras@empresa.com",
        subject="2 novas licitações",
        text="Olá",
        html="<p>Olá</p>",
    )

    assert message["To"] == "compras@empresa.com"
    assert message["Auto-Submitted"] == "auto-generated"
    assert [part.get_content_type() for part in message.iter_parts()] == [
        "text/plain",
        "text/html",
    ]


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []
    fail_with: ClassVar[Exception | None] = None

    def __init__(self, host: str, port: int, timeout: float, **kwargs: Any) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: object) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, message: EmailMessage) -> None:
        if FakeSMTP.fail_with:
            raise FakeSMTP.fail_with
        self.sent.append(message)


@pytest.fixture
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[FakeSMTP]]:
    FakeSMTP.instances = []
    FakeSMTP.fail_with = None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    yield FakeSMTP


def _message() -> EmailMessage:
    return build_message(sender="a@b.com", to="c@d.com", subject="s", text="t", html="<p>t</p>")


def test_smtp_com_starttls_e_login(fake_smtp: type[FakeSMTP]) -> None:
    sender = SmtpEmailSender("smtp.exemplo.com", 587, username="radar", password="x")

    sender.send(_message())

    smtp = fake_smtp.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.exemplo.com", 587)
    assert smtp.calls == ["starttls", "login:radar", "quit"]
    assert len(smtp.sent) == 1


def test_smtp_sem_criptografia_para_o_mailpit(fake_smtp: type[FakeSMTP]) -> None:
    SmtpEmailSender("mailpit", 1025, security="none").send(_message())

    assert fake_smtp.instances[0].calls == ["quit"]


def test_falha_do_smtp_vira_email_error(fake_smtp: type[FakeSMTP]) -> None:
    fake_smtp.fail_with = smtplib.SMTPRecipientsRefused({"c@d.com": (550, b"no")})

    with pytest.raises(EmailError, match=r"smtp\.exemplo\.com:465"):
        SmtpEmailSender("smtp.exemplo.com", 465, security="ssl").send(_message())


def test_smtp_desativado_sem_host() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://x")  # type: ignore[call-arg]
    assert SmtpEmailSender.from_settings(settings) is None

    settings = Settings(
        _env_file=None,
        database_url="postgresql://x",
        smtp_host="mailpit",
        smtp_port=1025,
        smtp_password="p",  # type: ignore[arg-type]
    )
    sender = SmtpEmailSender.from_settings(settings)
    assert sender is not None and (sender.host, sender.password) == ("mailpit", "p")


# --- Telegram --------------------------------------------------------------------------


def test_divide_mensagens_sem_cortar_blocos() -> None:
    blocks = ["cabeçalho", "a" * 60, "b" * 60, "c" * 60]

    messages = split_message(blocks, limit=125)

    assert messages == [f"cabeçalho\n\n{'a' * 60}", f"{'b' * 60}\n\n{'c' * 60}"]
    assert all(len(message) <= 125 for message in messages)
    assert split_message(["x" * 200], limit=50) == ["x" * 49 + "…"]
    assert split_message([]) == []


@pytest.fixture
def telegram() -> Iterator[TelegramClient]:
    client = TelegramClient(TOKEN, api_url=API)
    yield client
    client.close()


def test_envia_mensagem(telegram: TelegramClient) -> None:
    with respx.mock(base_url=API) as api:
        route = api.post(f"/bot{TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {}})
        )

        telegram.send_message("123", "<b>Olá</b>")

    body = route.calls.last.request.read().decode()
    assert '"chat_id":"123"' in body
    assert '"parse_mode":"HTML"' in body


def test_erro_do_telegram_nao_expoe_o_token(telegram: TelegramClient) -> None:
    with respx.mock(base_url=API) as api:
        api.post(f"/bot{TOKEN}/sendMessage").mock(
            return_value=httpx.Response(
                400, json={"ok": False, "description": "Bad Request: chat not found"}
            )
        )
        with pytest.raises(TelegramError, match="chat not found") as exc_info:
            telegram.send_message("999", "oi")

    assert TOKEN not in str(exc_info.value)


def test_falha_de_conexao_nao_expoe_o_token(telegram: TelegramClient) -> None:
    with respx.mock(base_url=API) as api:
        api.post(f"/bot{TOKEN}/sendMessage").mock(
            side_effect=httpx.ConnectError(f"falhou em {API}/bot{TOKEN}/sendMessage")
        )
        with pytest.raises(TelegramError) as exc_info:
            telegram.send_message("1", "oi")

    assert TOKEN not in str(exc_info.value)
    assert "***" in str(exc_info.value)


def test_telegram_desativado_sem_token() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://x", telegram_bot_token="")  # type: ignore[arg-type]

    assert TelegramClient.from_settings(settings) is None
