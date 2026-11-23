from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AlertMatch, Tender
from app.notifiers.email import EmailError
from app.notifiers.telegram import TelegramClient
from app.services import alerts as alert_service
from app.services.notifications import DigestContext, send_digests
from tests.integration.factories import PEDRA_PRETA, make_alert, make_tender

NOW = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)
CTX = DigestContext("https://radar.exemplo.com.br", ZoneInfo("America/Sao_Paulo"), "radar@x.com")
TOKEN = "999:TOKEN"
TELEGRAM_API = "https://telegram.test"


class FakeEmailSender:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.sent: list[EmailMessage] = []
        self.fail_for = fail_for or set()

    def send(self, message: EmailMessage) -> None:
        if message["To"] in self.fail_for:
            raise EmailError("caixa cheia")
        self.sent.append(message)


def _html(message: EmailMessage) -> str:
    part = message.get_body(("html",))
    assert part is not None
    return part.get_content()


def _text(message: EmailMessage) -> str:
    part = message.get_body(("plain",))
    assert part is not None
    return part.get_content()


@pytest.fixture
def telegram() -> Iterator[TelegramClient]:
    client = TelegramClient(TOKEN, api_url=TELEGRAM_API)
    yield client
    client.close()


@pytest.fixture
def scenario(db_session: Session) -> dict[str, int]:
    """Dois alertas com licitações pendentes (uma delas com caracteres especiais)."""
    ti = make_alert(
        db_session, name="TI & Redes", email="ti@empresa.com", keywords=["computador"],
        telegram_chat_id="12345",
    )  # fmt: skip
    obras = make_alert(db_session, name="Obras", email="obras@empresa.com", keywords=["reforma"])
    make_tender(
        db_session,
        object_description="Aquisição de computadores <desktop> & monitores",
        estimated_value=Decimal("150000"),
        proposals_close_at=datetime(2026, 12, 1, 13, 0, tzinfo=UTC),
    )
    make_tender(
        db_session,
        object_description="Locação de computador portátil",
        municipality=PEDRA_PRETA,
        estimated_value=None,
        proposals_close_at=datetime(2026, 11, 25, 13, 0, tzinfo=UTC),
    )
    make_tender(
        db_session, object_description="Reforma da escola municipal", estimated_value=Decimal("0")
    )
    make_alert(db_session, name="Inativo", keywords=["computador"], active=False)
    alert_service.match_new_tenders(db_session, created_since=NOW - timedelta(days=3650), now=NOW)
    return {"ti": ti.id, "obras": obras.id}


def test_um_email_por_alerta_com_as_licitacoes_pendentes(
    db_session: Session, scenario: dict[str, int]
) -> None:
    sender = FakeEmailSender()

    report = send_digests(db_session, email_sender=sender, telegram=None, ctx=CTX, now=NOW)

    assert report.ok
    assert (report.emails_sent, report.tenders_notified) == (2, 3)
    by_to = {message["To"]: message for message in sender.sent}
    assert set(by_to) == {"ti@empresa.com", "obras@empresa.com"}  # alerta inativo fica fora

    ti = by_to["ti@empresa.com"]
    assert ti["Subject"] == "Radar de Licitações: 2 novas licitações para “TI & Redes”"
    html = _html(ti)
    assert "Aquisição de computadores &lt;desktop&gt; &amp; monitores" in html  # escapado
    assert "R$ 150.000,00" in html
    assert "01/12/2026 10:00" in html  # 13:00 UTC no horário de Brasília
    assert "horário de Brasília" in html
    assert "https://radar.exemplo.com.br/licitacoes/" in html
    # prazo mais próximo primeiro
    assert html.index("computador portátil") < html.index("monitores")

    text = _text(ti)
    assert "Aquisição de computadores <desktop> & monitores" in text  # texto puro, sem escape
    assert "Valor estimado: Não informado" in text
    assert "&amp;" not in text


def test_nao_envia_a_mesma_licitacao_duas_vezes(
    db_session: Session, scenario: dict[str, int]
) -> None:
    send_digests(db_session, email_sender=FakeEmailSender(), telegram=None, ctx=CTX, now=NOW)

    again = FakeEmailSender()
    report = send_digests(db_session, email_sender=again, telegram=None, ctx=CTX, now=NOW)

    assert again.sent == []
    assert report.emails_sent == 0
    assert all(m.notified_at == NOW for m in db_session.scalars(select(AlertMatch)))


def test_falha_no_envio_mantem_pendente_para_o_proximo_resumo(
    db_session: Session, scenario: dict[str, int]
) -> None:
    report = send_digests(
        db_session,
        email_sender=FakeEmailSender(fail_for={"ti@empresa.com"}),
        telegram=None,
        ctx=CTX,
        now=NOW,
    )

    assert not report.ok
    assert report.emails_sent == 1  # o outro alerta não é prejudicado
    assert "caixa cheia" in report.failures[0]

    retry = FakeEmailSender()
    send_digests(db_session, email_sender=retry, telegram=None, ctx=CTX, now=NOW)
    assert [message["To"] for message in retry.sent] == ["ti@empresa.com"]


def test_sem_smtp_nada_e_marcado_como_enviado(
    db_session: Session, scenario: dict[str, int]
) -> None:
    report = send_digests(db_session, email_sender=None, telegram=None, ctx=CTX, now=NOW)

    assert report.emails_sent == 0
    assert all(m.notified_at is None for m in db_session.scalars(select(AlertMatch)))


def test_telegram_tem_controle_proprio_de_envio(
    db_session: Session, scenario: dict[str, int], telegram: TelegramClient
) -> None:
    with respx.mock(base_url=TELEGRAM_API) as api:
        route = api.post(f"/bot{TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        # E-mail falha, Telegram funciona: um canal não bloqueia o outro.
        report = send_digests(
            db_session,
            email_sender=FakeEmailSender(fail_for={"ti@empresa.com"}),
            telegram=telegram,
            ctx=CTX,
            now=NOW,
        )
        second = send_digests(db_session, email_sender=None, telegram=telegram, ctx=CTX, now=NOW)

    assert report.telegram_messages_sent == 1
    assert route.call_count == 1  # o segundo envio não repete nada pelo Telegram
    assert second.telegram_messages_sent == 0
    payload = route.calls.last.request.read().decode()
    assert '"chat_id":"12345"' in payload
    assert "TI &amp; Redes" in payload  # HTML do Telegram escapado
    assert "&lt;desktop&gt;" in payload

    ti_matches = db_session.scalars(
        select(AlertMatch).where(AlertMatch.alert_id == scenario["ti"])
    ).all()
    assert all(m.telegram_notified_at == NOW and m.notified_at is None for m in ti_matches)


def test_falha_no_telegram_mantem_pendente(
    db_session: Session, scenario: dict[str, int], telegram: TelegramClient
) -> None:
    with respx.mock(base_url=TELEGRAM_API) as api:
        api.post(f"/bot{TOKEN}/sendMessage").mock(
            return_value=httpx.Response(403, json={"ok": False, "description": "bot was blocked"})
        )
        report = send_digests(db_session, email_sender=None, telegram=telegram, ctx=CTX, now=NOW)

    assert "bot was blocked" in report.failures[0]
    assert TOKEN not in report.failures[0]
    assert all(m.telegram_notified_at is None for m in db_session.scalars(select(AlertMatch)))


def test_valor_zero_aparece_como_sigiloso(
    db_session: Session, scenario: dict[str, int], telegram: TelegramClient
) -> None:
    sender = FakeEmailSender()
    with respx.mock(base_url=TELEGRAM_API) as api:
        api.post(f"/bot{TOKEN}/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        send_digests(db_session, email_sender=sender, telegram=telegram, ctx=CTX, now=NOW)

    obras = next(m for m in sender.sent if m["To"] == "obras@empresa.com")
    assert "Sigiloso" in _html(obras)
    assert "Valor estimado: Sigiloso" in _text(obras)
    assert "R$ 0,00" not in _html(obras)


def test_licitacao_revogada_depois_do_casamento_nao_vai_no_resumo(
    db_session: Session, scenario: dict[str, int]
) -> None:
    reforma = db_session.scalars(
        select(Tender).where(Tender.object_description == "Reforma da escola municipal")
    ).one()
    reforma.status_code, reforma.status = 2, "Revogada"
    db_session.flush()
    sender = FakeEmailSender()

    report = send_digests(db_session, email_sender=sender, telegram=None, ctx=CTX, now=NOW)

    assert [message["To"] for message in sender.sent] == ["ti@empresa.com"]
    assert report.tenders_notified == 2
    # Continua pendente: se voltar a valer (fim de uma suspensão), sai no próximo resumo.
    pending = db_session.scalars(
        select(AlertMatch).where(
            AlertMatch.tender_id == reforma.id, AlertMatch.notified_at.is_(None)
        )
    ).all()
    assert len(pending) == 1

    reforma.status_code, reforma.status = 1, "Divulgada no PNCP"
    db_session.flush()
    send_digests(db_session, email_sender=sender, telegram=None, ctx=CTX, now=NOW)
    assert [message["To"] for message in sender.sent][-1] == "obras@empresa.com"
